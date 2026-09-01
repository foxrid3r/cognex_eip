from pycomm3 import CIPDriver

CAMERA_IP = "192.168.1.65"

with CIPDriver(CAMERA_IP) as camera:

    response = camera.generic_message(
        service=0x0E,        # Get_Attribute_Single
        class_code=0x78,     # Cognex Vision Object
        instance=1,
        attribute=6,         # Online
        connected=False,
        unconnected_send=False,
        route_path=False,
        data_type=None,
        name="Online"
    )

    print("Success:", bool(response))
    print("Raw value:", response.value)
    print("Raw hex:", bytes(response.value).hex(" "))