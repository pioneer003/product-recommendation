import os
import numpy as np
import pandas as pd
from math import sqrt
from sklearn.model_selection import train_test_split
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

os.environ["DJANGO_SETTINGS_MODULE"] = "product.settings"
import django
django.setup()
from user.models import Product, User, ComprehensiveScore


class MatrixFactorizationCF:
    """
    基于矩阵分解的协同过滤算法
    """

    def __init__(self, n_factors=20, learning_rate=0.01, regularization=0.02):
        """
        初始化模型参数

        参数:
            n_factors: 隐含特征维度
            learning_rate: 学习率
            regularization: 正则化系数
        """
        self.n_factors = n_factors
        self.learning_rate = learning_rate
        self.regularization = regularization

        self.user_factors = None  # 用户因子矩阵
        self.item_factors = None  # 物品因子矩阵
        self.item_names = None  # 物品名称列表

    def _init_matrices(self, user_item_matrix):
        """
        初始化用户和物品的隐含特征矩阵
        """
        n_users, n_items = user_item_matrix.shape

        # 随机初始化
        np.random.seed(42)
        self.user_factors = np.random.normal(scale=0.1, size=(n_users, self.n_factors))
        self.item_factors = np.random.normal(scale=0.1, size=(n_items, self.n_factors))

    def fit(self, user_item_df, test_data=None, epochs=200, verbose=True):
        """
        训练模型

        参数:
            user_item_df: 用户-物品评分矩阵的DataFrame
            test_data: 测试数据 [(user_idx, item_idx), ...]，用于计算测试RMSE
            epochs: 训练轮数
            verbose: 是否打印训练进度

        返回:
            训练历史 (train_rmse_history, test_rmse_history)
        """
        # 保存物品名称列表
        self.item_names = user_item_df.columns

        # 将评分矩阵转换为 numpy 数组
        user_item_matrix = user_item_df.values

        # 初始化模型参数
        self._init_matrices(user_item_matrix)

        # 创建评分矩阵的掩码 (标记哪些评分是有效的)
        mask = user_item_matrix > 0

        # 训练历史记录
        train_rmse_history = []
        test_rmse_history = []

        # 准备测试数据的真实评分
        if test_data:
            test_true_ratings = []
            test_user_items = []
            for user_idx, item_idx in test_data:
                test_true_ratings.append(user_item_matrix[user_idx, item_idx])
                test_user_items.append((user_idx, item_idx))
            # 将测试评分归一化到0-1范围，避免浮点溢出或梯度爆炸
            test_true_ratings = np.array(test_true_ratings)
            max_rating = max(np.max(user_item_matrix), 1.0)  # 避免除以0
            test_true_ratings = test_true_ratings / max_rating

        # 开始训练
        for epoch in range(1, epochs + 1):
            # 计算预测评分
            pred_matrix = self.predict_all()

            # 限制预测评分的范围，防止极端值
            pred_matrix = np.clip(pred_matrix, 0, 5)

            # 计算误差 (只考虑有评分的位置)
            error = mask * (user_item_matrix - pred_matrix)

            # 计算训练集 RMSE
            train_rmse = np.sqrt(np.sum(error ** 2) / np.sum(mask))
            train_rmse_history.append(train_rmse)

            # 计算测试集 RMSE
            if test_data:
                test_pred_ratings = np.array([pred_matrix[u, i] for u, i in test_user_items])
                # 将预测评分也归一化到相同的范围
                max_rating = max(np.max(user_item_matrix), 1.0)
                test_pred_ratings = test_pred_ratings / max_rating
                # 计算RMSE
                test_sqr_error = np.sum((test_true_ratings - test_pred_ratings) ** 2)
                test_rmse = np.sqrt(test_sqr_error / len(test_data))
                test_rmse_history.append(test_rmse)

                if verbose and (epoch == 1 or epoch % 10 == 0):
                    print(f"Epoch {epoch}/{epochs} - Train RMSE: {train_rmse:.4f}, Test RMSE: {test_rmse:.4f}")
            else:
                if verbose and (epoch == 1 or epoch % 10 == 0):
                    print(f"Epoch {epoch}/{epochs} - Train RMSE: {train_rmse:.4f}")

            # 更新用户和物品因子
            for u in range(user_item_matrix.shape[0]):
                for i in range(user_item_matrix.shape[1]):
                    if mask[u, i]:
                        # 计算误差梯度
                        e_ui = error[u, i]

                        # 更新用户和物品因子
                        user_f_old = self.user_factors[u].copy()
                        item_f_old = self.item_factors[i].copy()

                        # 梯度下降更新
                        self.user_factors[u] += self.learning_rate * (
                                    e_ui * item_f_old - self.regularization * user_f_old)
                        self.item_factors[i] += self.learning_rate * (
                                    e_ui * user_f_old - self.regularization * item_f_old)

        if test_data:
            return train_rmse_history, test_rmse_history
        else:
            return train_rmse_history

    def predict_all(self):
        """
        计算完整的预测评分矩阵
        """
        return np.dot(self.user_factors, self.item_factors.T)

    def predict(self, user_idx):
        """
        预测指定用户对所有物品的评分

        参数:
            user_idx: 用户索引

        返回:
            预测的评分数组
        """
        return np.dot(self.user_factors[user_idx], self.item_factors.T)

    def get_top_n_recommendations(self, user_idx, n=10, exclude_rated=True, user_item_matrix=None):
        """
        为指定用户获取前N个推荐物品

        参数:
            user_idx: 用户索引
            n: 推荐物品数量
            exclude_rated: 是否排除用户已评分的物品
            user_item_matrix: 用户-物品评分矩阵

        返回:
            推荐物品列表 [(item_id, score), ...]
        """
        # 获取预测评分
        predictions = self.predict(user_idx)

        # 排除用户已评分的物品
        if exclude_rated and user_item_matrix is not None:
            user_ratings = user_item_matrix[user_idx]
            predictions[user_ratings > 0] = -np.inf

        # 获取前N个推荐物品的索引
        top_indices = np.argsort(predictions)[::-1][:n]

        # 创建物品ID和预测分数的列表
        top_n = [(self.item_names[i], predictions[i]) for i in top_indices]

        return top_n


def evaluate_rmse(model, test_data, user_item_matrix):
    """
    计算测试集上的RMSE

    参数:
        model: 训练好的协同过滤模型
        test_data: 测试数据 [(user_idx, item_idx), ...]
        user_item_matrix: 完整的用户-物品矩阵

    返回:
        RMSE值
    """
    squared_error_sum = 0
    count = 0

    # 一次性计算所有用户的预测评分矩阵
    pred_matrix = model.predict_all()

    for user_idx, item_idx in test_data:
        # 计算预测评分与真实评分的差值平方
        pred_rating = pred_matrix[user_idx, item_idx]
        true_rating = user_item_matrix[user_idx, item_idx]

        squared_error_sum += (pred_rating - true_rating) ** 2
        count += 1

    # 计算RMSE
    rmse = sqrt(squared_error_sum / count) if count > 0 else float('nan')

    return rmse


def load_score_matrix_from_db():
    """从数据库 ComprehensiveScore 表加载用户-物品评分矩阵"""
    scores = ComprehensiveScore.objects.select_related("user", "product").all()
    if not scores.exists():
        raise RuntimeError("user_comprehensivescore 表为空，请先运行 compute_score.py")

    data = {}
    users = {}
    products = {}
    for s in scores:
        data[(s.user_id, s.product_id)] = s.score
        users[s.user_id] = s.user.name
        products[s.product_id] = s.product.name

    user_ids = sorted(users.keys())
    product_ids = sorted(products.keys())
    uid_to_idx = {uid: i for i, uid in enumerate(user_ids)}
    pid_to_idx = {pid: i for i, pid in enumerate(product_ids)}

    user_names = [users[uid] for uid in user_ids]
    product_names = [str(pid) for pid in product_ids]

    matrix = np.zeros((len(user_ids), len(product_ids)))
    for (uid, pid), score in data.items():
        matrix[uid_to_idx[uid], pid_to_idx[pid]] = score

    user_item = pd.DataFrame(matrix, index=user_names, columns=product_names)
    return user_item, user_ids


def recommend_by_collaborative_filtering(
        target_user_id=None,
        test_size=0.2,
        random_state=42,
        n_factors=20,
        learning_rate=0.002,
        regularization=0.02,
        epochs=200,
        top_n=15,
        plot_training=True,
        use_csv_fallback=True,
):
    """
    使用综合评分矩阵分解协同过滤进行Top-N推荐。

    参数:
        target_user_id: 为目标用户ID推荐。None=最后一个用户。
        use_csv_fallback: 数据库无数据时是否回退到 data.csv
    """
    # 1. 从数据库加载综合评分矩阵
    try:
        user_item, user_ids = load_score_matrix_from_db()
        print("数据来源: user_comprehensivescore 表 (评分 + 购买 + 评论 + 浏览)")
    except RuntimeError as e:
        if use_csv_fallback:
            print(f"数据库无数据 ({e})，回退到 data.csv")
            user_item = pd.read_csv("data.csv", encoding="gbk", index_col=0).fillna(0)
            user_ids = list(range(user_item.shape[0]))
        else:
            raise

    num_users, num_items = user_item.shape
    print(f"数据集维度: {num_users} 用户 x {num_items} 物品")

    # 2. 划分训练/测试集
    nonzero = [(u, i) for u in range(num_users) for i in range(num_items) if user_item.values[u, i] > 0]
    if len(nonzero) < 10:
        raise RuntimeError(f"有效评分太少 ({len(nonzero)} 条)，无法训练")
    train_pos, test_pos = train_test_split(nonzero, test_size=test_size, random_state=random_state)
    print(f"训练集样本数: {len(train_pos)}, 测试集样本数: {len(test_pos)}")

    # 3. 训练模型
    print(f"开始训练矩阵分解模型 (n_factors={n_factors}, epochs={epochs})")
    cf_model = MatrixFactorizationCF(n_factors=n_factors, learning_rate=learning_rate, regularization=regularization)
    train_rmse_history, test_rmse_history = cf_model.fit(user_item, test_data=test_pos, epochs=epochs)

    # 4. 评估
    final_test_rmse = evaluate_rmse(cf_model, test_pos, user_item.values)
    print(f"最终测试集RMSE: {final_test_rmse:.4f}")

    # 5. 绘制训练曲线
    if plot_training:
        plt.figure(figsize=(10, 6))
        plt.plot(range(1, epochs + 1), test_rmse_history, label='test RMSE')
        plt.title('RMSE Curve (Comprehensive Score)')
        plt.xlabel('epoch'), plt.ylabel('RMSE')
        plt.grid(True), plt.legend()
        plt.savefig('rmse_curve.png')
        print("RMSE 曲线已保存至 rmse_curve.png")

    # 6. 推荐
    if target_user_id is not None:
        user_idx = user_ids.index(target_user_id)
        target_name = User.objects.get(id=target_user_id).name
    else:
        user_idx = num_users - 1
        target_name = user_item.index[user_idx]

    top_items = cf_model.get_top_n_recommendations(user_idx, n=top_n, user_item_matrix=user_item.values)
    print(f"用户 [{target_name}] 的推荐结果 (item_id, score):")
    for item_id, score in top_items:
        print(f"  {item_id}: {score:.4f}")

    # 7. 返回 Product 列表
    recommended = []
    for item_id, _ in top_items:
        qs = Product.objects.filter(id=item_id)
        if qs.exists():
            recommended.append(qs.first())
    return recommended


if __name__ == "__main__":
    # 查询目标用户: 评论最多最活跃的是 ccc (user_id=38)
    recs = recommend_by_collaborative_filtering(
        target_user_id=38,
        epochs=200,
        n_factors=20,
        learning_rate=0.002,
        regularization=0.02,
    )
    print("\n最终推荐商品列表:")
    for p in recs:
        print(f"  [{p.id}] {p.name}")