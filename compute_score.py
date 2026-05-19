"""
多信号加权融合 — 综合评分计算脚本

信号来源:
  - user_rate          用户评分 (1-5)
  - user_product_collect 用户购买 (0/1)
  - user_comment       用户评论 + 点赞
  - user_view          用户浏览次数 (需先有该表数据)

公式:
  综合得分 = 0.4*评分 + 0.3*购买 + 0.2*评论互动 + 0.1*浏览
  所有信号先独立归一化到 0-5 区间, 再加权求和
"""
import os
import numpy as np
import pandas as pd
from collections import defaultdict
from math import log

os.environ["DJANGO_SETTINGS_MODULE"] = "product.settings"
import django
django.setup()
from user.models import (
    User, Product, Rate, Comment, ComprehensiveScore,
)
from django.db import connection


def minmax_norm(series, target_min=0, target_max=5):
    """将 series 归一化到 [target_min, target_max]"""
    smin, smax = series.min(), series.max()
    if smax == smin:
        return series.copy() * 0 + target_min
    return target_min + (series - smin) / (smax - smin) * (target_max - target_min)


def build_score_matrix():
    users = list(User.objects.all())
    products = list(Product.objects.all())
    user_ids = [u.id for u in users]
    product_ids = [str(p.id) for p in products]

    n_users = len(users)
    n_products = len(products)
    uid_to_idx = {uid: i for i, uid in enumerate(user_ids)}
    pid_to_idx = {str(pid): i for i, pid in enumerate(product_ids)}

    # ---- 1. 评分信号 (user_rate) ----
    rates = Rate.objects.all()
    rate_dict = defaultdict(float)
    for r in rates:
        rate_dict[(r.user_id, str(r.product_id))] = r.mark
    rate_matrix = np.zeros((n_users, n_products))
    for (uid, pid), mark in rate_dict.items():
        if uid in uid_to_idx and pid in pid_to_idx:
            rate_matrix[uid_to_idx[uid], pid_to_idx[pid]] = mark

    # ---- 2. 购买信号 (user_product_collect) ----
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, product_id FROM user_product_collect")
        collects = cursor.fetchall()
    buy_matrix = np.zeros((n_users, n_products))
    for uid, pid in collects:
        pid = str(pid)
        if uid in uid_to_idx and pid in pid_to_idx:
            buy_matrix[uid_to_idx[uid], pid_to_idx[pid]] = 1

    # ---- 3. 评论互动信号 (comment + good) ----
    comments = Comment.objects.all()
    comment_dict = defaultdict(float)
    for c in comments:
        key = (c.user_id, str(c.product_id))
        comment_dict[key] += 1 + log(1 + c.good)
    comment_matrix = np.zeros((n_users, n_products))
    for (uid, pid), val in comment_dict.items():
        if uid in uid_to_idx and pid in pid_to_idx:
            comment_matrix[uid_to_idx[uid], pid_to_idx[pid]] = val

    # ---- 4. 浏览信号 (user_view 表) ----
    view_matrix = np.zeros((n_users, n_products))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id, product_id, count FROM user_userview")
            views = cursor.fetchall()
        for uid, pid, cnt in views:
            pid = str(pid)
            if uid in uid_to_idx and pid in pid_to_idx:
                view_matrix[uid_to_idx[uid], pid_to_idx[pid]] = cnt
    except Exception:
        pass  # user_view 表暂时为空

    # ---- 5. 归一化 & 加权 ----
    W_RATE, W_BUY, W_COMMENT, W_VIEW = 0.4, 0.3, 0.2, 0.1
    combined = np.zeros((n_users, n_products))
    mask = np.zeros((n_users, n_products), dtype=bool)

    for name, weight, mat in [
        ("rate", W_RATE, rate_matrix),
        ("buy", W_BUY, buy_matrix),
        ("comment", W_COMMENT, comment_matrix),
        ("view", W_VIEW, view_matrix),
    ]:
        if mat.sum() > 0:
            flat = mat.flatten()
            nonzero = flat[flat > 0]
            if len(nonzero) > 0:
                normed = minmax_norm(mat, 0, 5)
                combined += weight * normed
                mask |= (mat > 0)

    # 最终得分范围控制在 0~5
    combined = np.clip(combined, 0, 5)

    # ---- 6. 入库 ----
    ComprehensiveScore.objects.all().delete()
    batch = []
    for i, uid in enumerate(user_ids):
        for j, pid in enumerate(product_ids):
            if mask[i, j]:
                batch.append(ComprehensiveScore(
                    user_id=uid, product_id=int(pid), score=round(float(combined[i, j]), 4)
                ))
    ComprehensiveScore.objects.bulk_create(batch, batch_size=500)

    # ---- 7. 输出汇总 ----
    nonzero_count = int(mask.sum())
    score_values = combined[mask]
    print(f"用户数: {n_users}  商品数: {n_products}")
    print(f"有效评分对: {nonzero_count}")
    print(f"得分范围: [{score_values.min():.2f}, {score_values.max():.2f}]")
    print(f"得分均值: {score_values.mean():.2f}")
    print(f"已写入 user_comprehensivescore 表")

    # 构造矩阵 DataFrame 打印预览
    df = pd.DataFrame(
        combined,
        index=[u.name for u in users],
        columns=product_ids,
    )
    return df


if __name__ == "__main__":
    df = build_score_matrix()
    print("\n=== 综合评分矩阵预览 ===")
    print(df.round(2).to_string(max_rows=8, max_cols=12))
