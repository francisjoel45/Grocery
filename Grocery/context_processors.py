def role_flags(request):
    is_shop_attendant = False
    if request.user.is_authenticated:
        is_shop_attendant = request.user.groups.filter(name='Shop Attendant').exists()
    return {'is_shop_attendant': is_shop_attendant}
