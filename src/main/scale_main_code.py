import datetime
import sys
import os
import time
import yaml 
from argparse import ArgumentParser
import serial
import serial.tools.list_ports
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import pandas as pd


SERIAL_PORT_DATA_RATE = 9600

POSSIBLE_DEVICE_PATHS = [
    "/dev/ttyACM0", 
    "/dev/ttyACM1", 
    # Debugging on local macOS machine - 
    "/dev/cu.usbmodem1101",
    "/dev/tty.usbmodem11101",
    "/dev/cu.usbmodem2401",
    "/dev/cu.usbmodem2301",
    # Debugging on a PC - 
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5" 
] 


strf_format = '%Y-%m-%d %H:%M' # This is the format for extracting datetime object from the 'Time' column string
scale_report_strf_time_format = '%Y-%m-%d %H:%M:%S' # This is the time format to be saved in the weight reports

def get_serial_device():
    """
    Get the device object for our serial port.
    """   
    for path in POSSIBLE_DEVICE_PATHS:
        try:
            ser = serial.Serial(path, SERIAL_PORT_DATA_RATE, timeout=1)
            print(f"\tSuccessfully opened serial port {path}")
            return ser
        except serial.SerialException:
            pass

    raise Exception(f"No valid serial port could be found! Tried the following - {POSSIBLE_DEVICE_PATHS}")


def read_config(path):
    """
    Reads a YAML config file from a given path, and returns its content as a dict.
    """
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            return data
    except Exception as err:
        raise Exception(f"Failed reading file `{path}` - {err}")    


def get_arduino_data(serial_device):
    """
    Read & parse data from the arduino device (via the serial port).
    We return a list of 9 items - 8 weight measurement values and one date&time string
    """
    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime(scale_report_strf_time_format)

    try:
        arduino_raw_data = serial_device.readline()
    except Exception as err:
        print(f"Failed reading data from Arduino! {err}")
        return None
    # print(arduino_raw_data)
    data_packet = parse_arduino_data(arduino_raw_data)

    # Verify that the data was read properly. 
    # If our data has less than the 8 values (one for each MUX channel), then there's been an error with reading the data 
    if (data_packet is None) or (len(data_packet)) < 8:
        print(f"Failed parsing data. Ignoring this record! (raw data was - {arduino_raw_data})")
        return None

    data_packet.append(formatted_time)
    return data_packet


def parse_arduino_data(arduino_raw_data):
    """
    this function accepts raw data from the serial port arduino it is connected to and edit it such that we will get numbers, with no space between lines.

    ###ARGS###
    arduino_raw_data - a one line with semicolon as delimeter between values for example : 10;30;14.6;0.00;1.11;....
    """
    try:
        raw_data = str(arduino_raw_data,'utf-8')
        data_packet = raw_data
        data_packet = data_packet.strip('\r\n')
        data_packet = data_packet.split(";")
        # Convert the raw data to a list of float values
        weights_packet = [float(x) for x in data_packet[:-1]]
    except Exception as err:
        print(f"Failed parsing a row - {raw_data}. Error - {err}")
        return None
    
    return weights_packet


if __name__ == "__main__":
    print("Hello! This is the scale system controller script!\n")

    ## Part 1 - parse the config file
    parser = ArgumentParser()

    # `config` actually IS a required variable, but this way it'll be easier to raise a custom error when it isn't supplied
    parser.add_argument("--config", required=False, help="The path for the config file we're working with.")
    args = parser.parse_args()

    #config_path = args.config
    config_path = r'/Users/cohenlab/Documents/Scale Methods Article/analyzer_codes/config_1.yaml'
    if config_path is None:
        raise Exception("No config file was supplied! Please rerun and add `--config=/path/to/config` ")

    config_data = read_config(config_path)
    print(f"Working with config file `{config_path}`, which contains - ")
    print(yaml.dump(config_data)) # This is just a trick to print the YAML content in a nicer way

        
    ## Part 2 - Connect to the serial device
    try:
        serial_device = get_serial_device()
        print("\tSuccessfully connected to Serial device")
    except Exception as err:
        print(f"Failed connecting to the Serial device - `{err}`")
        sys.exit(1)
    

    ## Part 2 - Initialize Slack
    SLACK_CHANNEL_ID = "" # The Slack channel id for the `monitor_alerts` channel
    SLACK_TOKEN = "" # combine the following lines in order to assemble the sack token
    try:
        slack_client = WebClient(token=SLACK_TOKEN)
        print("\tSuccessfully initialized Slack client")
    except Exception as err:
        print(f"Failed initializing Slack client - `{err}`")
        sys.exit(1)


    ## Part 3 - This is the main part of the code, which runs in a loop and reads data from sensors, and controls the light switch.

    scale_data = [] # This array will hande temporary scale data and will be reset once the defined time is over

    # if config_data["slackingTime"] is not None:
    #     last_slacking_time = datetime.datetime.now() # This timestamp will help indicate if we need to send the weight report to slack
    #     # Read user settings for time to send daily weight report to slack in HH:MM
    #     target_hour = int(config_data["slackingTime"][0:2])  # Example: 14 for 2 PM
    #     target_minute = int(config_data["slackingTime"][3:])  # Example: 30 for 2:30 PM

    if config_data["scaleDataReadingAndSaving"]: # If user chose to collect scale data, print the bird catalog (which bird is connected to which channel).
        bird_catalog = dict()
        for i in range(8):
            bird_id = config_data.get(f"channel{i}", 0)
            bird_catalog[f"channel{i}"] = bird_id
            if bird_id is not None:
                print(f"bird connected to channel{i}: {bird_id}")
        print("\n")
    
    first_contact = True

    while True: 
        while serial_device.in_waiting == 0: 
            if first_contact:
                print("system is setting up...\n")
                first_contact = False
            pass 
        
        # Part 3.1 - Read & aggregate data
        current_time = datetime.datetime.now()
        print(f"Current UTC time is {current_time}\n")

        minute_loop_start_time = datetime.datetime.now()
       
        # Part 3.2 - COLLECT DATA FOR 1 MINUTE
        while True:
            data = get_arduino_data(serial_device)
            # print("get arduino data: ", data)
            if data is None: # There was an error, moving on and ignoring this specific read
                continue

            scale_readings = [data[-1], data[:-1]]
            scale_data.append(scale_readings)

            if (datetime.datetime.now() - minute_loop_start_time).seconds >= 60:
                print("\tFinished collecting data for 1 minute")
                break
            time.sleep(1)

        # Part 3.3 - UPDATE WEIGHT REPORTS    
        print(f"\tWriting scale data to disk...")   

        # Generate base path for saving the weight reports to
        path_to_weight_reports = os.path.join(config_data["scaleOutputBasePath"], "weight_reports")

        scale_df = pd.DataFrame() # This dataframe will contain the current temporary time and weight data from all active scales

        # Create the time column once as it is similar for all
        scale_df['Time'] = [item[0] for item in scale_data] 

        # Iterate through all birds, if they have an active scale, add the new collected data to the weight report
        for i in range(8):
            if bird_catalog[f"channel{i}"] is None: # Config file has an empty field for this MUX channel
                continue
            else: # Config file has a bird name for current MUX channel...
                bird = bird_catalog[f"channel{i}"]
                print(f"\t\tbird '{bird}' in channel {i}, adding temporary scale data to report...")
                # Collect data for current bird into DataFrame.
                scale_df[bird] = [item[1][i] for item in scale_data]
                new_bird_data = scale_df[["Time", f"{bird}"]]
                # Build path to weight reports folder and create a folder for the current bird if it doesn't exist:
                path_to_current_bird = os.path.join(path_to_weight_reports, bird)
                os.makedirs(path_to_current_bird, exist_ok=True) 
            
                weight_report_filename = os.path.join(path_to_current_bird, f"{bird}_weight_report.csv")

                # Try reading existing weight report for current bird. 
                # If one exists, concatenate the new data and save the updated report. 
                # Else, save the current data as a new weight report.
                try:
                    existing_bird_data = pd.read_csv(weight_report_filename)
                    joint_bird_data = pd.concat([existing_bird_data, new_bird_data], ignore_index=True)
                    try:
                        joint_bird_data.to_csv(weight_report_filename, index=False)
                        print(f"\t\tSuccessfully added temporary scale data for bird: {bird}.")
                    except Exception as e:
                        print(f"\t\tAn error occurred while saving the new weight report for bird {bird}: {e}")
                except FileNotFoundError:
                    new_bird_data.to_csv(weight_report_filename, index=False)
                    print(f"\tSuccessfully created a new weight report for bird: {bird}. It was saved to: {weight_report_filename}.\n")
            print("\n")
        # Reset temporary scale data array
        scale_data = []


        # #**********SEND REPORTS TO SLACK**********
        # # Once a day, weight reports from all monitored birds will be slacked according to user choice.
        # # Check if user entered a time (HH:MM), If not - continue without slacking.
        # if config_data["slackingTime"] is not None:
        #     now = datetime.datetime.now()
        #     time_from_last_slacking = (now - last_slacking_time).total_seconds() / 60
        #     # Check if it's time to send daily weight reports to slack:
        #     # 1. Check if current hours & minutes match target hours & minutes.
        #     # 2. Sometimes a specific minute can be missed or repeated (because the minute data acquisition loop cannot be accurate to the second). 
        #     #    The second condition is there to catch a missed minute marker (target_minute+1) as long as no slack report was sent in the last minute(time_from_last_slacking).
        #     #    If target_minute was missed because the last 'now' was 09:59:59 and the new 'now' is 10:01:01 (the time 10:00 was missed), and the desired slacking time is 10:00, the condition will also work for 10:01 as long as there was no report sent in 10:00.
        #     #    A report could have been sent in 10:00, whereas the new 'now' will be 10:01 the condition would have worked unintendedly without the addition of the last condition. 
        #     if now.hour == target_hour and ((now.minute == target_minute or now.minute == target_minute+1) and time_from_last_slacking > 1.5):
        #         print(f"\t\tCurrent time is : {now.strftime('%H:%M')}, Slacking daily scale data...")
        #         # Generate daily data file for each bird, save it and send it to slack
        #         weight_report_output_path = os.path.join(config_data["scaleOutputBasePath"], "weight_reports")
            
        #         # upload the current scale report for each bird and send it to slack:   
        #         for key, birdname in bird_catalog.items():
        #             if birdname is None:
        #                 continue
        #             else:
        #                 path_to_current_bird = os.path.join(weight_report_output_path, birdname)
        #                 weight_report_filename = find_single_csv_file(path_to_current_bird, name_type='full')

        #                 # send daily csv report to slack
        #                 if config_data["sendWeightReportToSlack"]:
        #                     try:
        #                         send_file_to_slack(slack_client, weight_report_filename)
        #                         last_slacking_time = datetime.datetime.now()
        #                         print(f"\t\tSuccesfully slacked daily weight report for bird {birdname}!")
        #                     except Exception as e:
        #                             print(f"\t\t\tAn error occurred while slacking daily weight report for bird {birdname}: {e}")

        #                 if config_data["saveFig"] or config_data["sendFigToSlack"]:
        #                     print(f"\t\t Sending figure to slack...")
        #                     date_today = datetime.datetime.now().strftime("%Y_%m_%d") # current date
        #                     data = pd.read_csv(weight_report_filename) # read latest weight report to pandas dataframe

        #                     # convert the name of the scale readings column from 'birdname' to 'Weight' before sending it to 'plot_Data' function
        #                     data['Weight'] = data[birdname] 
        #                     data_to_fig = data[["Time", "Weight"]]

        #                     hours_back = int(config_data["hours_back"])

        #                     if config_data["saveFig"]:
        #                         saveFig=True
        #                         figure_filename = os.path.join(path_to_current_bird, f"figure_{date_today}_{birdname}.png") 
        #                     else:
        #                         saveFig=False

        #                     fig, ax = plot_data(data_to_fig, date_fmt = scale_report_strf_time_format, save=saveFig, fig_name_path=figure_filename, birdname=birdname, hours_back=hours_back)

        #                     if config_data["sendFigToSlack"]:
        #                         send_figure_to_slack(slack_client, fig)
        #                         last_slacking_time = datetime.datetime.now()



