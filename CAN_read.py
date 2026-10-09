import can
import odrive

odrv0 = odrive.find_sync()
bus = can.interface.Bus(bustype='slcan', channel = 'can0', bitrate = 500000)
msg = can.Message(arbiration_id=0x000, data = [], is_extended_id=False)

def main()
    while True:
        try:
            bus.send(msg)
            print("Message sent on {}".format(bus.channel_info))
        except can.CanError as e:
            print("Error occurred: {}".format(e))

if __name__ == "__main__":
    print("running odrive CAN test")