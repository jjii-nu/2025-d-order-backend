from django.db import models
from booth.models import Booth, Table

# Create your models here.
class Menu(models.Model):
    CATEGORY_CHOICES = ( #둘 중 하나로 저장 카테고리 
        ("음료", "음료"),
        ("메뉴", "메뉴"),
    )
    id = models.AutoField(primary_key=True)
    booth_id = models.ForeignKey(Booth, on_delete=models.CASCADE)
    menu_name = models.CharField(max_length=20)
    menu_description = models.CharField(max_length=30)
    menu_category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    menu_price = models.IntegerField()
    menu_amount = models.IntegerField()
    menu_remain = models.IntegerField()
    menu_image = models.ImageField(upload_to='menu_images/', blank=True, null=True)
    def __str__(self):
        return self.menu_name


class Cart(models.Model):
    id = models.AutoField(primary_key=True)
    table_id = models.ForeignKey(Table, on_delete=models.CASCADE)
    cart_status = models.BooleanField(default=False)
    total_price = models.IntegerField()

    
class Order(models.Model):
    id = models.AutoField(primary_key=True)
    cart_id = models.ForeignKey(Cart, on_delete=models.CASCADE)
    menu_id = models.ForeignKey(Menu, on_delete=models.CASCADE)
    menu_num = models.IntegerField()
    order_status = models.CharField(max_length=50)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
