import bluetooth

def normalize_uuid_str(uuid_str):
    if isinstance(uuid_str, str):
        uuid_str = int("0x"+uuid_str,0)
    return bluetooth.UUID(uuid_str)

