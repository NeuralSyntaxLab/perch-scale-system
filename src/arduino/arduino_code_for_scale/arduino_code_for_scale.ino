/***************************************************************************
* THIS IS THE MAIN ARDUINO CODE FOR THE BIRD SCALE SYSTEM

This code reads data from up to 8 scale devices using Sparkfun QwiicScale MUX breadboard. Each weight measurement is received through one of eight different ports available on the MUX board.
Weight measurements from all channels are collected every second and sent to an external python script running on a computer connected to the Arduino.

For calibrating the scales, load 'arduin_code_calibrate' from the adjacent folder in the repository and follow the instructions.

See Scale System Guide located in the main repository for more information.

NOTE: PLEASE MAKE SURE THAT THE FOLLOWING LIBRARY IS INSTALLED IN ARDUINO IDE:
SparkFun I2C Mux Arduino Library

***************************************************************************/

#include <Wire.h>
#include <EEPROM.h> //Needed to record user settings
#include <SparkFun_I2C_Mux_Arduino_Library.h>
#include <SparkFun_Qwiic_Scale_NAU7802_Arduino_Library.h>

#define DHT22_PIN 8
QWIICMUX myMux;
NAU7802 myScale;

//EEPROM locations to store 20-byte variables
#define LOCATION_CALIBRATION_FACTOR(port) (port * 20) // Float, requires 4 bytes, plus extra space.
#define LOCATION_ZERO_OFFSET(port) (LOCATION_CALIBRATION_FACTOR(port) + 8) // //Must be more than 4 away from previous spot. Long, requires 4 bytes of EEPROM
bool settingsDetected = false; //Used to prompt user to calibrate their scale

const int numScales = 8; // Number of Qwiic Scale ports available
int samplesToTake = 8; //Number of samples to average over when calculating weight using getWeight function. Default is 8

int incomingByte = 0; // Variable that will contain user input

unsigned long seconds = 875L;
unsigned long minutes = seconds * 1;
unsigned long DelayRate = minutes;


void setup() {
  // pinMode(LIGHT_SWITCH_PIN, OUTPUT);
  // pinMode(ldrPin, INPUT);
  Wire.begin();

  Serial.begin(9600);

  // myScale setup and scale parameters acquisition
  if (!myMux.begin()) {
  Serial.println("Mux not detected. Make sure scale system is connected properly and try again. Swich to arduino_code_0 to monitor DHT data alone, or to arduino_code_2 to test and calibrate scale.");
  delay(DelayRate);
  }
  else {
  // Serial.println("Mux detected");
  for (int i = 0; i < numScales; ++i) {
    myMux.enablePort(i);
    myScale.begin();

    if (myScale.begin()) {

      myScale.setSampleRate(NAU7802_SPS_320); //Increase to max sample rate
      myScale.calibrateAFE(); //Re-cal analog front end when we change gain, sample rate, or channel 
    }
    myMux.disablePort(i);
  } 
  } 
}

void loop() {
  for (int i = 0; i < numScales; ++i) {
    myMux.setPort(i); // Activate communication with active scale #[i], disable all other ports
 
    if (myScale.available() == true) {
      readSystemSettings(i);
      float currentScaleReading = myScale.getWeight(false,samplesToTake);
      if (!isnan(currentScaleReading)) {
        Serial.print(currentScaleReading, 2);
        Serial.print(";");   
      } else {
        Serial.print(0);
        Serial.print(";");
      } 
    } 
    else {
      Serial.print(0);
      Serial.print(";");
    }
  }
  Serial.println("");
  myMux.setPort(-1); // disable all ports

  delay(DelayRate); //wait 1 second until next data reading
}

//Scale functions for communicating with EEPROM(non-vlatile memory of arduino)

//Reads the current system settings from EEPROM
//If anything looks weird, reset setting to default value
void readSystemSettings(int scalePort) //REQUIRED to read an already-calibrated system settings (zero offset and calibration factor)
{
  float settingCalibrationFactor; //Value used to convert the load cell reading to lbs or kg
  long settingZeroOffset; //Zero value that is found when scale is tared

  //Look up the calibration factor
  EEPROM.get(LOCATION_CALIBRATION_FACTOR(scalePort), settingCalibrationFactor);
  if (settingCalibrationFactor == 0xFFFFFFFF)
  {
    settingCalibrationFactor = 0; //Default to 0
    EEPROM.put(LOCATION_CALIBRATION_FACTOR(scalePort), settingCalibrationFactor);
  }

  //Look up the zero tare point
  EEPROM.get(LOCATION_ZERO_OFFSET(scalePort), settingZeroOffset);
  if (settingZeroOffset == 0xFFFFFFFF)
  {
    settingZeroOffset = 1000L; //Default to 1000 so we don't get inf
    EEPROM.put(LOCATION_ZERO_OFFSET(scalePort), settingZeroOffset);
  }

  //Pass these values to the library
  myScale.setCalibrationFactor(settingCalibrationFactor);
  myScale.setZeroOffset(settingZeroOffset);

  settingsDetected = true; //Assume for the moment that there are good cal values
  if (settingCalibrationFactor < 0.1 || settingZeroOffset == 1000)
    settingsDetected = false; //Defaults detected. Prompt user to cal scale.
}