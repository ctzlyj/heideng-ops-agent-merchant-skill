"""Compare the official shop observation with this profile's previous registration."""


def registration_issue(registry, profile, identity):
    if not isinstance(registry, dict) or not isinstance(registry.get('profiles'), dict):
        return '原店铺登记不能读取，未覆盖。'
    profiles = registry['profiles']
    if profile not in profiles:
        return None
    registered = profiles[profile]
    if not isinstance(registered, dict):
        return '原 Profile 的店铺登记不能读取，未覆盖。'
    for key in ('shopId', 'venderId', 'shopName'):
        if key == 'shopName' and not (registered.get('lastVerifiedAt') or registered.get('shopId')):
            continue  # A new profile may still carry the user's working name.
        if registered.get(key) and str(registered[key]) != str(identity.get(key) or ''):
            return '官方核店与原 Profile 的已登记身份不一致。'
    return None
