import os
from math import sqrt
import operator

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt

# 配置 Django 环境（如在 Django 项目中运行）
os.environ["DJANGO_SETTINGS_MODULE"] = "product.settings"
import django
django.setup()
from user.models import Product  # 确保 Product 模型存在


class AutoRec(nn.Module):
    def __init__(self, num_users, hidden_features):
        super(AutoRec, self).__init__()
        # Encoder: 使用 ReLU 激活以缓解梯度消失
        self.encoder = nn.Sequential(
            nn.Linear(num_users, hidden_features, bias=True),
            nn.ReLU()
        )
        # Decoder: 包装为 Sequential，兼容旧模型 state_dict 键名
        self.decoder = nn.Sequential(
            nn.Linear(hidden_features, num_users, bias=True)
        )

    def forward(self, x):
        return self.decoder(self.encoder(x))


def l2_regularization(model):
    l2 = 0.0
    for name, param in model.named_parameters():
        if not name.endswith('bias'):
            l2 += torch.norm(param, p=2)
    return l2


def loss_function(y_true, y_pred, mask, lamda, model):
    """
    计算带 L2 正则的 MSE 损失
    """
    mse = F.mse_loss(y_pred * mask, y_true * mask)
    reg = 0.5 * lamda * l2_regularization(model)
    return mse + reg


def recommend_by_autorec(
    data_path="data.csv",
    model_path="autorec1.pth",
    hidden_dim=50,
    lr=0.003,
    epochs=100,
    lamda=0.04,
    test_size=0.2,
    random_state=42
):
    """
    使用 AutoRec 对最后一个用户进行 Top-N 推荐，并返回对应的 Product 对象列表。
    同时跟踪并绘制每个 epoch 在测试集上的平滑 RMSE 曲线。
    """
    # 1. 读取数据并初始化矩阵
    df = pd.read_csv(data_path, encoding="gbk")
    num_users = df.shape[0]
    num_items = df.shape[1] - 1
    user_item = pd.read_csv(data_path, encoding="gbk", index_col=0).fillna(0)
    R = torch.from_numpy(user_item.values).float()

    # 2. 划分训练/测试位置并构造 masks
    nonzero = [(u, i) for u in range(num_users) for i in range(num_items) if R[u, i] > 0]
    train_pos, test_pos = train_test_split(nonzero, test_size=test_size, random_state=random_state)
    train_mask = torch.zeros_like(R, dtype=torch.bool)
    test_mask = torch.zeros_like(R, dtype=torch.bool)
    for u, i in train_pos: train_mask[u, i] = True
    for u, i in test_pos:  test_mask[u, i] = True

    # 3. 初始化模型、优化器和调度器
    model = AutoRec(num_users, hidden_dim)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=10, verbose=True)

    # 4. 加载旧模型（仅加载形状匹配的参数）
    if os.path.exists(model_path):
        checkpoint = torch.load(model_path, map_location="cpu")
        model_dict = model.state_dict()
        filtered = {k: v for k, v in checkpoint.items() if k in model_dict and v.size() == model_dict[k].size()}
        model_dict.update(filtered)
        model.load_state_dict(model_dict)
        print(f"Loaded {len(filtered)}/{len(checkpoint)} parameters from checkpoint.")

    # 5. 训练阶段：跟踪训练损失和测试 RMSE
    train_losses = []
    test_rmses  = []

    for epoch in range(1, epochs + 1):
        model.train()
        total_mse, total_reg = 0.0, 0.0
        for i in range(num_items):
            col = R[:, i].unsqueeze(0)
            mcol = train_mask[:, i].unsqueeze(0)
            pred = model(col)
            mse = F.mse_loss(pred * mcol, col * mcol)
            reg = 0.5 * lamda * l2_regularization(model)
            loss = mse + reg
            optimizer.zero_grad(); loss.backward(); optimizer.step()
            total_mse += mse.item(); total_reg += reg.item()
        avg_mse  = total_mse / num_items
        avg_reg  = total_reg / num_items
        avg_loss = avg_mse + avg_reg
        train_losses.append(avg_loss)
        scheduler.step(avg_loss)

        # 测试集 RMSE 评估
        model.eval()
        total_se, count = 0.0, 0
        with torch.no_grad():
            for i in range(num_items):
                col  = R[:, i].unsqueeze(0)
                pred = model(col).squeeze()
                true = col.squeeze()
                mask_i = test_mask[:, i]
                if mask_i.sum() > 0:
                    se = F.mse_loss(pred[mask_i], true[mask_i], reduction="sum").item()
                    total_se += se; count += mask_i.sum().item()
        epoch_rmse = sqrt(total_se / count) if count > 0 else float('nan')
        test_rmses.append(epoch_rmse)

        if epoch == 1 or epoch % 10 == 0:
            lr_now = optimizer.param_groups[0]['lr']
            print(f"Epoch {epoch}/{epochs} | Train Loss: {avg_loss:.4f} | Test RMSE: {epoch_rmse:.4f} | LR: {lr_now:.6f}")

    # 保存模型
    torch.save(model.state_dict(), model_path)

    # 6. 绘制测试集平滑 RMSE 曲线
    # 使用滚动平均进行平滑（window=5）
    rmses_smooth = pd.Series(test_rmses).rolling(window=5, min_periods=1, center=True).mean()
    plt.figure()
    plt.plot(range(1, epochs + 1), rmses_smooth, linewidth=2)
    plt.title('Smoothed Test RMSE over Epochs')
    plt.xlabel('Epoch')
    plt.ylabel('Test RMSE')
    plt.grid(True)
    plt.show()

    # 7. 最终推荐 Top-15
    user_idx = num_users - 1
    scores = {}
    with torch.no_grad():
        for i in range(num_items):
            col = R[:, i].unsqueeze(0)
            scores[user_item.columns[i]] = model(col).squeeze()[user_idx].item()
    top15 = sorted(scores.items(), key=operator.itemgetter(1), reverse=True)[:15]
    print("推荐结果 (item_id, score):", top15)

    # 8. 获取 Product 对象并返回
    recommended = []
    for item_id, _ in top15:
        qs = Product.objects.filter(id=item_id)
        if qs.exists(): recommended.append(qs.first())
    return recommended


if __name__ == "__main__":
    recs = recommend_by_autorec()
    print("最终返回的 Product 对象列表：", recs)
