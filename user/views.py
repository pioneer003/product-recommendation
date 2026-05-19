import logging
import csv
from functools import wraps

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from rest_framework.renderers import JSONRenderer

from cache_keys import USER_CACHE, ITEM_CACHE
from recommend_products import recommend_by_autorec
from .forms import *

logger = logging.getLogger()
logger.setLevel(level=0)


def login_in(func):  # 验证用户是否登录
    @wraps(func)
    def wrapper(*args, **kwargs):
        request = args[0]
        is_login = request.session.get("login_in")
        if is_login:
            return func(*args, **kwargs)
        else:
            return redirect(reverse("login"))

    return wrapper


def products_paginator(products, page):  # 设置页码
    paginator = Paginator(products, 6)
    if page is None:
        page = 1
    products = paginator.page(page)
    return products


class JSONResponse(HttpResponse):
    def __init__(self, data, **kwargs):
        content = JSONRenderer().render(data)
        kwargs["content_type"] = "application/json"
        super(JSONResponse, self).__init__(content, **kwargs)


def login(request):  # 登录功能
    if request.method == "POST":
        form = Login(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            result = User.objects.filter(username=username)
            if result:
                user = User.objects.get(username=username)
                if user.password == password:
                    request.session["login_in"] = True
                    request.session["user_id"] = user.id
                    request.session["name"] = user.name
                    return redirect(reverse("all_product"))
                else:
                    return render(
                        request, "user/login.html", {"form": form, "message": "密码错误"}
                    )
            else:
                return render(
                    request, "user/login.html", {"form": form, "message": "账号不存在"}
                )
    else:
        form = Login()
        return render(request, "user/login.html", {"form": form})


def register(request):  # 注册功能
    if request.method == "POST":
        form = RegisterForm(request.POST)
        error = None
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password2"]
            email = form.cleaned_data["email"]
            name = form.cleaned_data["name"]
            phone = form.cleaned_data["phone"]
            address = form.cleaned_data["address"]
            User.objects.create(
                username=username,
                password=password,
                email=email,
                name=name,
                phone=phone,
                address=address,
            )
            # 根据表单数据创建一个新的用户
            return redirect(reverse("login"))  # 跳转到登录界面
        else:
            return render(
                request, "user/register.html", {"form": form, "error": error}
            )  # 表单验证失败返回一个空表单到注册页面
    form = RegisterForm()
    return render(request, "user/register.html", {"form": form})


def logout(request):
    if not request.session.get("login_in", None):  # 不在登录状态跳转回首页
        return redirect(reverse("index"))
    request.session.flush()  # 清除session信息
    return redirect(reverse("index"))


def all_product(request):  # 所有商品
    products = Product.objects.annotate(user_collector=Count('collect')).order_by('-user_collector')
    paginator = Paginator(products, 9)
    current_page = request.GET.get("page", 1)
    products = paginator.page(current_page)
    return render(request, "user/item.html", {"products": products, "title": "所有商品"})


def search(request):  # 搜索
    if request.method == "POST":  # 如果搜索界面
        key = request.POST["search"]
        request.session["search"] = key  # 记录搜索关键词解决跳页问题
    else:
        key = request.session.get("search")  # 得到关键词
    products = Product.objects.filter(
        Q(name__icontains=key) | Q(intro__icontains=key) | Q(director__icontains=key)
    )  # 进行内容的模糊搜索
    page_num = request.GET.get("page", 1)
    products = products_paginator(products, page_num)
    return render(request, "user/item.html", {"products": products})


def product(request, product_id): # 商品详情页
    product = Product.objects.get(pk=product_id)
    product.num += 1
    product.save()
    comments = product.comment_set.order_by("-create_time")
    user_id = request.session.get("user_id")
    product_rate = Rate.objects.filter(product=product).all().aggregate(Avg('mark'))
    if product_rate:
        product_rate = product_rate['mark__avg']
    if user_id is not None:
        user_rate = Rate.objects.filter(product=product, user_id=user_id).first()
        user = User.objects.get(pk=user_id)
        is_collect = product.collect.filter(id=user_id).first()
    return render(request, "user/product.html", locals())


@login_in
# 在打分的时候清楚缓存
def score(request, product_id):  # 打分功能
    user_id = request.session.get("user_id")
    # user = User.objects.get(id=user_id)
    product = Product.objects.get(id=product_id)
    score = float(request.POST.get("score"))
    get, created = Rate.objects.get_or_create(user_id=user_id, product=product, defaults={"mark": score})
    if created:
        print('create data')
        # 清理缓存
        user_cache = USER_CACHE.format(user_id=user_id)
        item_cache = ITEM_CACHE.format(user_id=user_id)
        cache.delete(user_cache)
        cache.delete(item_cache)
        print('cache deleted')

        with open("./data.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_data = []
            index = 0
            for row in reader.reader:
                for i in range(90):
                    if row[i] == str(product_id):
                        index = i
                        print('index:',index)
                old_data.append(row)

        print(old_data)
        print(index)
        print('---'*30)
        old_data[11][index] = int(score)

        with open('./data.csv', 'w', encoding='utf-8', newline='') as f:
            write = csv.writer(f)  # 创建writer对象

            # 写内容，writerrow 一次只写入一行
            for data in old_data:
                write.writerow(data)

    return redirect(reverse("product", args=(product_id,)))


@login_in
def commen(request, product_id):  # 评论功能
    user = User.objects.get(id=request.session.get("user_id"))
    product = Product.objects.get(id=product_id)
    # product.score.com += 1
    # product.score.save()
    comment = request.POST.get("comment")
    Comment.objects.create(user=user, product=product, content=comment)
    return redirect(reverse("product", args=(product_id,)))


def good(request, commen_id, product_id):  # 给评论点赞
    commen = Comment.objects.get(id=commen_id)
    commen.good += 1
    commen.save()
    return redirect(reverse("product", args=(product_id,)))


@login_in
def collect(request, product_id):  # 加入购物车
    user = User.objects.get(id=request.session.get("user_id"))
    product = Product.objects.get(id=product_id)
    product.collect.add(user)
    product.save()
    return redirect(reverse("product", args=(product_id,)))


@login_in
def decollect(request, product_id):  # 取消加购
    user = User.objects.get(id=request.session.get("user_id"))
    product = Product.objects.get(id=product_id)
    product.collect.remove(user)
    # product.rate_set.count()
    product.save()
    return redirect(reverse("product", args=(product_id,)))


@login_in
def personal(request):  # 个人中心
    user = User.objects.get(id=request.session.get("user_id"))
    if request.method == "POST":
        form = Edit(instance=user, data=request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("personal"))
        else:
            return render(
                request, "user/personal.html", {"message": "修改失败", "form": form}
            )
    form = Edit(instance=user)
    return render(request, "user/personal.html", {"form": form})


@login_in
def mycollect(request):  # 个人中心——我的购物车
    user = User.objects.get(id=request.session.get("user_id"))
    product = user.product_set.all()
    return render(request, "user/mycollect.html", {"product": product})

@login_in
def my_comments(request):  # 个人中心——我的评论
    user = User.objects.get(id=request.session.get("user_id"))
    comments = user.comment_set.all()
    print('comment:', comments)
    return render(request, "user/my_comment.html", {"comments": comments})


@login_in
def delete_comment(request, comment_id): # 个人中心——我的评论——删除评论
    Comment.objects.get(pk=comment_id).delete()
    return redirect(reverse("my_comments"))


@login_in
def my_rate(request):  # 个人中心——我的评分
    user = User.objects.get(id=request.session.get("user_id"))
    rate = user.rate_set.all()
    return render(request, "user/my_rate.html", {"rate": rate})

# 购买最多
def hot_product(request):
    page_number = request.GET.get("page", 1)
    products = Product.objects.annotate(user_collector=Count('collect')).order_by('-user_collector')[:10]
    products = products_paginator(products[:10], page_number)
    return render(request, "user/item.html", {"products": products, "title": "最热商品"})


# 评分最多
def most_mark(request):
    page_number = request.GET.get("page", 1)
    products = Product.objects.all().annotate(num_mark=Count('rate')).order_by('-num_mark')[:10]
    products = products_paginator(products, page_number)
    return render(request, "user/item.html", {"products": products, "title": "评分最多"})


# 浏览最多
def most_view(request):
    page_number = request.GET.get("page", 1)
    products = Product.objects.annotate(user_collector=Count('num')).order_by('-num')[:10]
    products = products_paginator(products[:10], page_number)
    return render(request, "user/item.html", {"products": products, "title": "浏览最多"})

# 最新商品
def latest_product(request):
    page_number = request.GET.get("page", 1)
    products = products_paginator(Product.objects.order_by("-id")[:10], page_number)
    return render(request, "user/item.html", {"products": products, "title": "最新商品"})

def kindof(request):
    tags = Tags.objects.all()
    return render(request, "user/kindof.html", {"tags": tags})


def kind(request, kind_id):
    tags = Tags.objects.get(id=kind_id)
    products = tags.product_set.all()
    page_num = request.GET.get("page", 1)
    products = products_paginator(products, page_num)
    return render(request, "user/kind.html", {"products": products, "title": tags})


@login_in
def reco_by_random(request):
    page = request.GET.get("page", 1)
    product_list = Product.objects.order_by('?')[:10]
    print("product_list:", product_list)
    products = products_paginator(product_list, page)
    path = request.path
    title = "随机推荐"
    return render(
        request, "user/item.html", {"products": products, "path": path, "title": title}
    )


@login_in
def user_recommend(request):
    page = request.GET.get("page", 1)
    user_id = request.session.get("user_id")
    cache_key = ITEM_CACHE.format(user_id=user_id)
    product_list = cache.get(cache_key)
    if product_list is None:
        product_list = recommend_by_autorec()
        cache.set(cache_key, product_list, 60 * 5)
        print('设置缓存')
    else:
        print('缓存命中!')
    products = products_paginator(product_list, page)
    path = request.path
    title = "依据喜好推荐"
    return render(
        request, "user/item.html", {"products": products, "path": path, "title": title}
    )
