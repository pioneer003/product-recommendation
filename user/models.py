from django.db import models
from django.db.models import Avg


class User(models.Model):
    username = models.CharField(max_length=32, unique=True, verbose_name="账号")
    password = models.CharField(max_length=32, verbose_name="密码")
    phone = models.CharField(max_length=32, verbose_name="手机号码")
    name = models.CharField(max_length=32, verbose_name="名字", unique=True)
    address = models.CharField(max_length=32, verbose_name="地址")
    email = models.EmailField(verbose_name="邮箱")

    class Meta:
        verbose_name_plural = "用户"
        verbose_name = "用户"

    def __str__(self):
        return self.name


class Tags(models.Model):
    name = models.CharField(max_length=32, verbose_name="标签", unique=True)

    class Meta:
        verbose_name = "标签"
        verbose_name_plural = "标签"

    def __str__(self):
        return self.name


class Product(models.Model):
    tags = models.ManyToManyField(Tags, verbose_name='标签', blank=True)
    collect = models.ManyToManyField(User, verbose_name="购买者", blank=True)
    sump = models.IntegerField(verbose_name="购买人数", default=0)
    name = models.CharField(verbose_name="商品名称", max_length=32, unique=True)
    director = models.CharField(verbose_name="商家名称", max_length=128)
    country = models.CharField(verbose_name="国家", max_length=32)
    years = models.CharField(verbose_name="年份", max_length=32)
    leader = models.CharField(verbose_name="价格", max_length=128)
    d_rate = models.CharField(verbose_name="淘宝评分", max_length=32)
    intro = models.TextField(verbose_name="描述")
    num = models.IntegerField(verbose_name="浏览量", default=0)
    pic = models.FileField(verbose_name="封面图片", max_length=64, upload_to='product_cover', default='')


    class Meta:
        verbose_name = "商品"
        verbose_name_plural = "商品"

    def __str__(self):
        return self.name


class UserView(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="商品")
    count = models.IntegerField(verbose_name="浏览次数", default=1)
    last_view_time = models.DateTimeField(verbose_name="最后浏览时间", auto_now=True)

    class Meta:
        verbose_name = "用户浏览"
        verbose_name_plural = "用户浏览"
        unique_together = ("user", "product")


class ComprehensiveScore(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="商品")
    score = models.FloatField(verbose_name="综合得分")
    updated_at = models.DateTimeField(verbose_name="更新时间", auto_now=True)

    class Meta:
        verbose_name = "综合评分"
        verbose_name_plural = "综合评分"
        unique_together = ("user", "product")


class Rate(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, blank=True, null=True, verbose_name="商品id"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, blank=True, null=True, verbose_name="用户id",
    )
    mark = models.FloatField(verbose_name="评分")
    create_time = models.DateTimeField(verbose_name="发布时间", auto_now_add=True)

    @property
    def avg_mark(self):
        average = Rate.objects.all().aggregate(Avg('mark'))['mark__avg']
        return average

    class Meta:
        verbose_name = "评分信息"
        verbose_name_plural = verbose_name


class Comment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    content = models.CharField(max_length=64, verbose_name="内容")
    create_time = models.DateTimeField(auto_now_add=True)
    good = models.IntegerField(verbose_name="点赞", default=0)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="商品")

    class Meta:
        verbose_name = "评论"
        verbose_name_plural = verbose_name


