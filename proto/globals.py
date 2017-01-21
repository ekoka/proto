from .local import Local

local = Local()
# creating a bunch of proxies
request = local('request')
current_user = local('current_user')
