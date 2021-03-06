"""senet in pytorch



[1] Jie Hu, Li Shen, Samuel Albanie, Gang Sun, Enhua Wu

    Squeeze-and-Excitation Networks
    https://arxiv.org/abs/1709.01507
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import math

subnetnum=0

class MyPassLayer(nn.Module):
    def __init__(self,inival=1.2):
        super(MyPassLayer, self).__init__()
        self.scale = nn.Parameter(torch.ones(1)*inival)
    def forward(self, x):
        out=x*self.scale
        return out

class BasicResidualSEBlock(nn.Module):

    expansion = 1

    def __init__(self, in_channels, out_channels, stride, r=16,bn=False):
        super().__init__()
        global subnetnum
        subnetnum += 1.
        self.residual = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, stride=stride, padding=1),
            nn.ReLU(inplace=True),
            
            nn.Conv2d(out_channels, out_channels * self.expansion, 3, padding=1),
            MyPassLayer(1.2**2/subnetnum),
            nn.ReLU(inplace=True)
        )

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels * self.expansion:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels * self.expansion, 1, stride=stride),
                MyPassLayer()
            )
        
        self.squeeze = nn.AdaptiveAvgPool2d(1)
        self.excitation = nn.Sequential(
            nn.Linear(out_channels * self.expansion, out_channels * self.expansion // r),
            nn.ReLU(inplace=True),
            nn.Linear(out_channels * self.expansion // r, out_channels * self.expansion),
            nn.Sigmoid()
        )

    def forward(self, x):
        shortcut = self.shortcut(x)
        residual = self.residual(x)

        squeeze = self.squeeze(residual)
        squeeze = squeeze.view(squeeze.size(0), -1)
        excitation = self.excitation(squeeze)
        excitation = excitation.view(residual.size(0), residual.size(1), 1, 1)

        x = residual * excitation.expand_as(residual) + shortcut

        return F.relu(x)

class BottleneckResidualSEBlock(nn.Module):

    expansion = 4

    def __init__(self, in_channels, out_channels, stride, r=16,bn=False):
        super().__init__()
        global subnetnum
        subnetnum += 1.
        self.bn=bn
        if self.bn:
            Layer0=nn.BatchNorm2d
        else:
            Layer0=None
        self.residual = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 1),
            nn.ReLU(inplace=True),

            nn.Conv2d(out_channels, out_channels, 3, stride=stride, padding=1),
            nn.ReLU(inplace=True),

            nn.Conv2d(out_channels, out_channels * self.expansion, 1),
            MyPassLayer(1.2**3/subnetnum),
            nn.ReLU(inplace=True)
        )

        self.squeeze = nn.AdaptiveAvgPool2d(1)
        self.excitation = nn.Sequential(
            nn.Linear(out_channels * self.expansion, out_channels * self.expansion // r),
            nn.ReLU(inplace=True),
            nn.Linear(out_channels * self.expansion // r, out_channels * self.expansion),
            nn.Sigmoid()
        )

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels * self.expansion:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels * self.expansion, 1, stride=stride),
                MyPassLayer()
            )

    def forward(self, x):

        shortcut = self.shortcut(x)

        residual = self.residual(x)
        squeeze = self.squeeze(residual)
        squeeze = squeeze.view(squeeze.size(0), -1)
        excitation = self.excitation(squeeze)
        excitation = excitation.view(residual.size(0), residual.size(1), 1, 1)

        x = residual * excitation.expand_as(residual) + shortcut

        return F.relu(x)

class SEResNet(nn.Module):

    def __init__(self, block, block_num, class_num=100,CBN=True):
        super().__init__()
        self.CBN=CBN
        self.in_channels = 64
        global subnetnum
        subnetnum =0
        self.pre = nn.Sequential(
            nn.Conv2d(3, 64, 3, padding=1),
            nn.ReLU(inplace=True)
        )

        self.stage1 = self._make_stage(block, block_num[0], 64, 1)
        self.stage2 = self._make_stage(block, block_num[1], 128, 2)
        self.stage3 = self._make_stage(block, block_num[2], 256, 2)
        self.stage4 = self._make_stage(block, block_num[3], 516, 2)

        self.linear = nn.Linear(self.in_channels, class_num)
        if self.CBN:
            self.lastbn=nn.BatchNorm1d(class_num,affine=False)  

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.in_channels
                m.weight.data.normal_(0, math.sqrt(2.0 / n))
                if not m.bias is None:
                    m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                n = m.in_features
                m.weight.data.normal_(0, math.sqrt(2. / n))
                if not m.bias is None:
                    m.bias.data.zero_()
            elif isinstance(m, nn.BatchNorm2d):
                print('+1')
                m.weight.data.fill_(1.)
                m.bias.data.fill_(0.)
            elif isinstance(m, nn.BatchNorm1d) and m.affine:
                m.weight.data.fill_(1)
                m.bias.data.zero_()      
    def forward(self, x):
        x = self.pre(x)

        x = self.stage1(x)
        x = self.stage2(x)
        x = self.stage3(x)
        x = self.stage4(x)

        x = F.adaptive_avg_pool2d(x, 1)
        x = x.view(x.size(0), -1)

        x = self.linear(x)
        if self.CBN:
            x = self.lastbn(x)

        return x

    
    def _make_stage(self, block, num, out_channels, stride):

        layers = []
        layers.append(block(self.in_channels, out_channels, stride,bn=True))
        self.in_channels = out_channels * block.expansion

        while num - 1:
            layers.append(block(self.in_channels, out_channels, 1,bn=num%5==4))
            num -= 1
        #layers.append(nn.BatchNorm2d( out_channels * block.expansion))
        return nn.Sequential(*layers)
        
def seresnet18():
    return SEResNet(BasicResidualSEBlock, [2, 2, 2, 2])

def seresnet34():
    return SEResNet(BasicResidualSEBlock, [3, 4, 6, 3])

def seresnet50():
    return SEResNet(BottleneckResidualSEBlock, [3, 4, 6, 3])

def seresnet101():
    return SEResNet(BottleneckResidualSEBlock, [3, 4, 23, 3])

def seresnet152():
    return SEResNet(BottleneckResidualSEBlock, [3, 8, 36, 3])
