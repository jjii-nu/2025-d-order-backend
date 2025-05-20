from rest_framework.views import APIView
from rest_framework import mixins, generics
from rest_framework.response import Response
from rest_framework import status
from manager.models import Manager
from booth.models import Booth, Table
from order.models import Cart, Order, Menu
from django.shortcuts import get_object_or_404
from .serializers import *
from django.db.models import Sum, F
from django.utils.timezone import now
from rest_framework.permissions import IsAuthenticated

class AddToCartView(APIView):
    def post(self, request):

        serializer = AddToCartRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "status": "fail",
                "message": serializer.errors,
                "code": 400
            }, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        booth_id = request.data.get('booth_id')
        table_num = request.data.get('table_num')
        menu_id = request.data.get('menu_id')
        menu_num = int(request.data.get('menu_num', 1))

        # 1. booth 존재 확인
        booth = get_object_or_404(Booth, id=booth_id)

        # 2. table 조회 or 생성
        table, _ = Table.objects.get_or_create(
            booth_id=booth,
            table_num=table_num,
            defaults={'table_status': 'active'}
        )

        # 3. cart_status=False인 Cart 조회 or 생성
        cart, _ = Cart.objects.get_or_create(
            table_id=table,
            cart_status=False,
            defaults={'total_price': 0}
        )

        # 4. menu 확인
        menu = get_object_or_404(Menu, id=menu_id)

        # 5. 동일한 메뉴가 이미 주문되었는지 확인
        try:
            order = Order.objects.get(cart_id=cart, menu_id=menu)
            total_menu_num = order.menu_num + menu_num

            if total_menu_num > menu.menu_remain:
                return Response({
                    "status": "fail",
                    "message": "주문 수량이 재고를 초과했습니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

            order.menu_num = total_menu_num
            order.save()

        except Order.DoesNotExist:
            if menu_num > menu.menu_remain:
                return Response({
                    "status": "fail",
                    "message": "주문 수량이 재고를 초과했습니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

            order = Order.objects.create(
                cart_id=cart,
                menu_id=menu,
                menu_num=menu_num,
                order_status='장바구니',
            )

        # 6. cart 가격 갱신
        cart.total_price += menu.menu_price * menu_num
        cart.save()

        # 7. 응답
        return Response({
            "status": "success",
            "message": "장바구니에 메뉴가 담겼습니다.",
            "code": 201,
            "data": {
                "cart_id": cart.id,
                "table_id": table.id,
                "menu_id": menu.id,
                "menu_num": order.menu_num
            }
        }, status=status.HTTP_201_CREATED)

class TableCartView(APIView):
    def get(self, request, table_id):
        table = get_object_or_404(Table, id=table_id)

        try:
            cart = Cart.objects.get(table_id=table, cart_status=False)
        except Cart.DoesNotExist:
            return Response({
                "status": "fail",
                "message": "장바구니가 존재하지 않습니다.",
                "code": 404
            }, status=status.HTTP_404_NOT_FOUND)

        orders = Order.objects.filter(cart_id=cart).select_related('menu_id')
        serializer = CartSummarySerializer(orders, many=True)

        return Response({
            "status": "success",
            "message": "장바구니 조회 완료",
            "code": 200,
            "data": {
                "cart_id": cart.id,
                "table_id": table.id,
                "total_price": cart.total_price,
                "orders": serializer.data
            }
        }, status=status.HTTP_200_OK)
    
class TableOrderView(APIView):
    def get(self, request, table_id):
        table = get_object_or_404(Table, id=table_id)

        carts = Cart.objects.filter(table_id=table, cart_status=True)

        if not carts.exists():
            return Response({
                "stats": "fail",
                "message": "완료된 주문이 없습니다",
                "code": 404
            }, status=status.HTTP_404_NOT_FOUND)
        
        orders = Order.objects.filter(cart_id__in=carts).select_related('menu_id').order_by('-created_at')
        serializer = TableOrderSerializer(orders, many=True)

        return Response({
            "status": "success",
            "message": "주문 내역 조회 완료",
            "code": 200,
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
class BoothOrderView(APIView):
    def get(self, request, booth_id):
        booth = get_object_or_404(Booth, id=booth_id)

        menus = Menu.objects.filter(booth_id=booth)

        order_complete_orders = Order.objects.filter(
            menu_id__in=menus,
            order_status='order_complete'
        )

        # 총 매출 계산 
        total_revenue_qs = Order.objects.filter(
            menu_id__in=menus,
            order_status__in=['order_complete', 'served_complete']
        ).annotate(
            item_total=F('menu_num') * F('menu_id__menu_price')
        ).aggregate(total=Sum('item_total'))

        total_revenue = total_revenue_qs['total'] or 0

        serializer = BoothOrderSerializer(order_complete_orders, many=True)
        return Response({
            "status": "success",
            "message": "주문 목록 및 매출 조회 완료",
            "code": 200,
            "data": {
                "total_revenue": total_revenue,
                "orders": serializer.data
            }
        }, status=status.HTTP_200_OK)
    
class OrderFixView(APIView):
    def patch(self, request, cart_id):
        cart = get_object_or_404(Cart, id=cart_id)

        cart_status = request.data.get('cart_status')
        
        if cart.cart_status:
            return Response({
                "status": "fail",
                "message": "이미 확정된 주문입니다.",
                "code": 400
            }, status=status.HTTP_400_BAD_REQUEST)
        
        orders = Order.objects.filter(cart_id=cart).select_related('menu_id')

        for order in orders:
            menu = order.menu_id
            if order.menu_num > menu.menu_remain:
                return Response({
                    "status": "fail",
                    "message": f"재고가 부족합니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

        now_time = now()
        for order in orders:
            menu = order.menu_id
            menu.menu_remain -= order.menu_num
            menu.save()

            order.order_status = 'order_complete'
            order.created_at = now_time
            order.save()

        cart.cart_status = True
        cart.save()


        return Response({
            "status": "success",
            "message": "주문이 확정되었습니다.",
            "code": 200,
            "data": {
                "cart_id": cart.id,
                "cart_status": cart.cart_status
            }
        }, status=status.HTTP_200_OK)
    
class UpdateOrderStatusView(APIView):
    def patch(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)

        new_status = request.data.get('order_status')

        order.order_status = 'served_complete'
        order.save()

        serializer = TableOrderSerializer(order)

        return Response({
            "status": "success",
            "message": "서빙 완료로 변경되었습니다.",
            "code": 200,
            "data": serializer.data
        }, status=status.HTTP_200_OK)

#메뉴 등록 기능
class MenuCreateView(APIView):
    permission_classes = [IsAuthenticated]  #로그인한 사람만 등록 가능
    #메뉴 등록
    def post(self, request):
        serializer = MenuSerializer(data=request.data)
        manager = Manager.objects.get(user=request.user)
        if serializer.is_valid():
            menu = serializer.save(booth_id=manager.booth)
            return Response({
                "status": "success",
                "message": "메뉴가 등록되었습니다.",
                "code": 201,
                "data": {
                    "booth_id": menu.booth_id.id,
                    "menu_id": menu.id,
                    "menu_name": menu.menu_name,
                    "menu_category": menu.menu_category,
                    "menu_price": menu.menu_price,
                    "menu_amount": menu.menu_amount,
                    "menu_remain": menu.menu_remain,
                    "menu_image": menu.menu_image.url if menu.menu_image else None
                }
            }, status=status.HTTP_201_CREATED)
        return Response({
            "status": "fail",
            "message": "유효하지 않은 요청입니다.",
            "code": 400,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
#메뉴 수정,삭제
class MenuPatchDeleteView(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView
):
    queryset = Menu.objects.all()
    serializer_class = MenuSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = 'menu_id'  # URL에서 <menu_id> 가져오기

    def get_queryset(self):
        manager = Manager.objects.get(user=self.request.user)
        return Menu.objects.filter(booth_id=manager.booth)
    
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)
    
class MenuListView(APIView):
    def get(self, request):
        manager = Manager.objects.get(user=request.user)

        # 로그인한 매니저의 부스 메뉴만 가져오기
        menus = Menu.objects.filter(booth_id=manager.booth)

        # 정렬 우선순위 설정
        category_order = {
            "테이블 이용료": 0,
            "메뉴": 1,
            "음료": 2
        }

        # 정렬 수행
        sorted_menus = sorted(
            menus,
            key=lambda m: (
                category_order.get(m.menu_category, 99),
                -m.menu_price,
                m.id
            )
        )

        # 직렬화
        serializer = MenuSerializer(sorted_menus, many=True)

        return Response({
            "status": "success",
            "message": "메뉴 리스트 조회 성공",
            "code": 200,
            "data": serializer.data
        }, status=200)

class UpdateOrderQuantityView(APIView):
    def patch(self, request, order_id):
        try:
            # 1. Order 객체 가져오기
            order = get_object_or_404(Order, id=order_id)
            menu = order.menu_id
            cart = order.cart_id

            # 2. 요청 데이터
            menu_num = request.data.get("menu_num")

            if menu_num is None:
                return Response({
                    "status": "fail",
                    "message": "menu_num이 누락되었습니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

            # 3. menu_num 유효성 검사
            try:
                menu_num = int(menu_num)
            except ValueError:
                return Response({
                    "status": "fail",
                    "message": "menu_num은 숫자여야 합니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

            if menu_num < 1:
                return Response({
                    "status": "fail",
                    "message": "수량은 1개 이상이어야 합니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

            # 4. 테이블 이용료 확인
            if menu.menu_name == "테이블 이용료" or menu.menu_category == "테이블 이용료" or menu.menu_category.lower() == "seat":
                return Response({
                    "status": "fail",
                    "message": "테이블 이용료 항목은 변경할 수 없습니다.",
                    "code": 403
                }, status=status.HTTP_403_FORBIDDEN)

            # 5. 재고 초과 여부 확인
            if menu_num > menu.menu_remain:
                return Response({
                    "status": "fail",
                    "message": f"재고({menu.menu_remain})보다 많은 수량은 담을 수 없습니다.",
                    "code": 400
                }, status=status.HTTP_400_BAD_REQUEST)

            # 6. 수량 변경
            order.menu_num = menu_num
            order.save()

            # 7. 카트 총 가격 재계산
            orders = Order.objects.filter(cart_id=cart)
            total_price = sum(o.menu_id.menu_price * o.menu_num for o in orders)
            cart.total_price = total_price
            cart.save()

            return Response({
                "status": "success",
                "message": "수량이 성공적으로 변경되었습니다.",
                "code": 200,
                "data": {
                    "order_id": order.id,
                    "menu_num": order.menu_num
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "status": "fail",
                "message": str(e),
                "code": 500
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    def delete(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)
        menu = order.menu_id
        cart = order.cart_id

        # 테이블 이용료 항목 삭제 방지
        if menu.menu_name == "테이블 이용료" or menu.menu_category == "테이블 이용료" or menu.menu_category.lower() == "seat":
            return Response({
                "status": "fail",
                "message": "테이블 이용료 항목은 삭제할 수 없습니다.",
                "code": 403
            }, status=status.HTTP_403_FORBIDDEN)

        # 삭제 수행
        order.delete()

        # cart 총합 재계산
        remaining_orders = Order.objects.filter(cart_id=cart)
        total_price = sum(o.menu_id.menu_price * o.menu_num for o in remaining_orders)
        cart.total_price = total_price
        cart.save()

        return Response({
            "status": "success",
            "message": "해당 항목이 삭제되었습니다.",
            "code": 204
        }, status=status.HTTP_204_NO_CONTENT)

class FinalizeOrderView(APIView):
    def post(self, request):
        table_id = request.data.get("table_id")

        if table_id is None:
            return Response({
                "status": "fail",
                "message": "table_id가 필요합니다.",
                "code": 400
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            cart = Cart.objects.get(table_id=table_id, cart_status=True)
        except Cart.DoesNotExist:
            return Response({
                "status": "fail",
                "message": "진행 중인 장바구니가 없습니다.",
                "code": 404
            }, status=status.HTTP_404_NOT_FOUND)

        # 장바구니 확정 처리
        cart.cart_status = False
        cart.save()

        return Response({
            "status": "success",
            "message": "주문이 완료되었습니다.",
            "code": 201,
            "data": {
                "cart_id": cart.id,
                "table_id": cart.table_id.id,
                "total_price": cart.total_price
            }
        }, status=status.HTTP_201_CREATED)

class LastOrderView(APIView):
    def get(self, request, table_id):
        # cart_status=False인 것 중에서 가장 최근 cart 하나 조회
        cart = Cart.objects.filter(table_id=table_id, cart_status=False).order_by('-id').first()

        if not cart:
            return Response({
                "status": "fail",
                "message": "해당 테이블의 완료된 주문이 없습니다.",
                "code": 404
            }, status=status.HTTP_404_NOT_FOUND)

        # 해당 cart에 연결된 주문들
        orders = Order.objects.filter(cart_id=cart)
        orders_serialized = TableOrderSerializer(orders, many=True).data

        return Response({
            "cart_id": cart.id,
            "table_id": cart.table_id.id,
            "cart_status": cart.cart_status,
            "total_price": cart.total_price,
            "orders": orders_serialized
        }, status=status.HTTP_200_OK)

class OrderCheckView(APIView):
    def post(self, request, table_id):
        password = request.data.get("order_check_password")

        if not password:
            return Response({
                "status": "error",
                "message": "비밀번호가 누락되었습니다.",
                "code": 400,
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        # 현재 로그인한 매니저 조회
        try:
            manager = Manager.objects.get(user=request.user)
        except Manager.DoesNotExist:
            return Response({
                "status": "error",
                "message": "접근 권한이 없습니다.",
                "code": 403,
                "data": None
            }, status=status.HTTP_403_FORBIDDEN)

        # 비밀번호 검증
        if manager.order_check_password != password:
            return Response({
                "status": "error",
                "message": "비밀번호가 올바르지 않습니다.",
                "code": 401,
                "data": None
            }, status=status.HTTP_401_UNAUTHORIZED)

        # 테이블의 진행 중인 cart 찾기
        try:
            cart = Cart.objects.get(table_id=table_id, cart_status=True)
        except Cart.DoesNotExist:
            return Response({
                "status": "error",
                "message": "진행 중인 주문이 없습니다.",
                "code": 404,
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        # cart 상태 변경
        cart.cart_status = False
        cart.save()

        # 가장 최신 order 하나 상태 변경
        order = Order.objects.filter(cart_id=cart).order_by('-created_at').first()
        if order:
            order.order_status = "completed"
            order.save()

        return Response({
            "status": "success",
            "message": "결제가 확인되었습니다.",
            "code": 200,
            "data": None
        }, status=status.HTTP_200_OK)