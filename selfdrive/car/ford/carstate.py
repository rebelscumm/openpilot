from cereal import car
from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.ford.fordcan import CanBus
from openpilot.selfdrive.car.ford.values import DBC, CarControllerParams, FordFlags, FordConfig, BUTTONS
from openpilot.selfdrive.car.interfaces import CarStateBase

GearShifter = car.CarState.GearShifter
TransmissionType = car.CarParams.TransmissionType


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint]["pt"])

    self.bluecruise_cluster_present = FordConfig.BLUECRUISE_CLUSTER_PRESENT # Sets the value of whether the car has the blue cruise cluster
    if CP.transmissionType == TransmissionType.automatic:
      if CP.flags & FordFlags.CANFD:
        self.shifter_values = can_define.dv["Gear_Shift_by_Wire_FD1"]["TrnRng_D_RqGsm"]
      elif CP.flags & FordFlags.ALT_STEER_ANGLE:
        self.shifter_values = can_define.dv["TransGearData"]["GearLvrPos_D_Actl"]
      else:
        self.shifter_values = can_define.dv["PowertrainData_10"]["TrnRng_D_Rq"]

    self.cluster_min_speed = CV.KPH_TO_MS * 1.5
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.

    self.vehicle_sensors_valid = False
    self.steering_angle_offset_deg = 0

    self.prev_distance_button = 0
    self.distance_button = 0

    self.lkas_enabled = None
    self.prev_lkas_enabled = None
    self.v_limit = 0

    self.button_states = {button.event_type: False for button in BUTTONS}
    self.up_down_button = [0, 0, 0, 0]

  def update(self, cp, cp_cam):
    ret = car.CarState.new_message()

    self.prev_mads_enabled = self.mads_enabled
    self.prev_lkas_enabled = self.lkas_enabled

    if self.CP.flags & FordFlags.ALT_STEER_ANGLE:
      self.vehicle_sensors_valid = (
        int((cp.vl["ParkAid_Data"]["ExtSteeringAngleReq2"] + 1000) * 10) not in (32766, 32767)
        and cp.vl["ParkAid_Data"]["EPASExtAngleStatReq"] == 0
        and cp.vl["ParkAid_Data"]["ApaSys_D_Stat"] in (0, 1)
      )
    else:
      # Occasionally on startup, the ABS module recalibrates the steering pinion offset, so we need to block engagement
      # The vehicle usually recovers out of this state within a minute of normal driving
      self.vehicle_sensors_valid = cp.vl["SteeringPinion_Data"]["StePinCompAnEst_D_Qf"] == 3

    # car speed
    ret.vEgoRaw = cp.vl["BrakeSysFeatures"]["Veh_V_ActlBrk"] * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    if self.CP.flags & FordFlags.CANFD:
      ret.vEgoCluster = ((cp.vl["Cluster_Info_3_FD1"]["DISPLAY_SPEED_SCALING"]/100) * cp.vl["EngVehicleSpThrottle2"]["Veh_V_ActlEng"] +
                         cp.vl["Cluster_Info_3_FD1"]["DISPLAY_SPEED_OFFSET"]) * CV.KPH_TO_MS

    ret.yawRate = cp.vl["Yaw_Data_FD1"]["VehYaw_W_Actl"]
    ret.standstill = cp.vl["DesiredTorqBrk"]["VehStop_D_Stat"] == 1

    # gas pedal
    ret.gas = cp.vl["EngVehicleSpThrottle"]["ApedPos_Pc_ActlArb"] / 100.
    ret.gasPressed = ret.gas > 1e-6

    # brake pedal
    ret.brake = cp.vl["BrakeSnData_4"]["BrkTot_Tq_Actl"] / 32756.  # torque in Nm
    ret.brakePressed = cp.vl["EngBrakeData"]["BpedDrvAppl_D_Actl"] == 2
    ret.parkingBrake = cp.vl["DesiredTorqBrk"]["PrkBrkStatus"] in (1, 2)

    # steering wheel
    if self.CP.flags & FordFlags.ALT_STEER_ANGLE:
      steering_angle_init = cp.vl["SteeringPinion_Data_Alt"]["StePinRelInit_An_Sns"]
      if self.vehicle_sensors_valid:
        steering_angle_est = cp.vl["ParkAid_Data"]["ExtSteeringAngleReq2"]
        self.steering_angle_offset_deg = steering_angle_est - steering_angle_init
      ret.steeringAngleDeg = steering_angle_init + self.steering_angle_offset_deg
    else:
      ret.steeringAngleDeg = cp.vl["SteeringPinion_Data"]["StePinComp_An_Est"]
    ret.steeringTorque = cp.vl["EPAS_INFO"]["SteeringColumnTorque"]
    ret.steeringPressed = self.update_steering_pressed(abs(ret.steeringTorque) > CarControllerParams.STEER_DRIVER_ALLOWANCE, 5)
    ret.steerFaultTemporary = cp.vl["EPAS_INFO"]["EPAS_Failure"] == 1
    ret.steerFaultPermanent = cp.vl["EPAS_INFO"]["EPAS_Failure"] in (2, 3)
    ret.espDisabled = cp.vl["Cluster_Info1_FD1"]["DrvSlipCtlMde_D_Rq"] != 0  # 0 is default mode

    if self.CP.flags & FordFlags.CANFD:
      # this signal is always 0 on non-CAN FD cars
      ret.steerFaultTemporary |= cp.vl["Lane_Assist_Data3_FD1"]["LatCtlSte_D_Stat"] not in (1, 2, 3)

    # cruise state
    is_metric = cp.vl["INSTRUMENT_PANEL"]["METRIC_UNITS"] == 1 if not self.CP.flags & FordFlags.CANFD else False
    ret.cruiseState.speed = cp.vl["EngBrakeData"]["Veh_V_DsplyCcSet"] * (CV.KPH_TO_MS if is_metric else CV.MPH_TO_MS)
    ret.cruiseState.enabled = cp.vl["EngBrakeData"]["CcStat_D_Actl"] in (4, 5)
    ret.cruiseState.available = cp.vl["EngBrakeData"]["CcStat_D_Actl"] in (3, 4, 5)
    ret.cruiseState.nonAdaptive = cp.vl["Cluster_Info1_FD1"]["AccEnbl_B_RqDrv"] == 0
    ret.cruiseState.standstill = cp.vl["EngBrakeData"]["AccStopMde_D_Rq"] == 3
    ret.accFaulted = cp.vl["EngBrakeData"]["CcStat_D_Actl"] in (1, 2)

    if self.CP.flags & FordFlags.CANFD:
      ret.cruiseState.speedLimit = self.update_traffic_signals(cp_cam)

    if not self.CP.openpilotLongitudinalControl:
      ret.accFaulted = ret.accFaulted or cp_cam.vl["ACCDATA"]["CmbbDeny_B_Actl"] == 1

    # gear
    if self.CP.transmissionType == TransmissionType.automatic:
      if self.CP.flags & FordFlags.CANFD:
        gear = self.shifter_values.get(cp.vl["Gear_Shift_by_Wire_FD1"]["TrnRng_D_RqGsm"])
      elif self.CP.flags & FordFlags.ALT_STEER_ANGLE:
           gear = self.shifter_values.get(cp.vl["TransGearData"]["GearLvrPos_D_Actl"])
      else:
        gear = self.shifter_values.get(cp.vl["PowertrainData_10"]["TrnRng_D_Rq"])

      ret.gearShifter = self.parse_gear_shifter(gear)
    elif self.CP.transmissionType == TransmissionType.manual:
      ret.clutchPressed = cp.vl["Engine_Clutch_Data"]["CluPdlPos_Pc_Meas"] > 0
      if bool(cp.vl["BCM_Lamp_Stat_FD1"]["RvrseLghtOn_B_Stat"]):
        ret.gearShifter = GearShifter.reverse
      else:
        ret.gearShifter = GearShifter.drive

    # Buttons
    for button in BUTTONS:
      state = (cp.vl[button.can_addr][button.can_msg] in button.values)
      if self.button_states[button.event_type] != state:
        event = car.CarState.ButtonEvent.new_message()
        event.type = button.event_type
        event.pressed = state
        self.button_events.append(event)
      self.button_states[button.event_type] = state

    # safety
    ret.stockFcw = bool(cp_cam.vl["ACCDATA_3"]["FcwVisblWarn_B_Rq"])
    ret.stockAeb = bool(cp_cam.vl["ACCDATA_2"]["CmbbBrkDecel_B_Rq"])

    # button presses
    ret.leftBlinker = ret.leftBlinkerOn = cp.vl["Steering_Data_FD1"]["TurnLghtSwtch_D_Stat"] == 1
    ret.rightBlinker = ret.rightBlinkerOn = cp.vl["Steering_Data_FD1"]["TurnLghtSwtch_D_Stat"] == 2
    # TODO: block this going to the camera otherwise it will enable stock TJA
    ret.genericToggle = bool(cp.vl["Steering_Data_FD1"]["TjaButtnOnOffPress"])
    self.prev_distance_button = self.distance_button
    self.distance_button = cp.vl["Steering_Data_FD1"]["AccButtnGapTogglePress"]

    # lock info
    ret.doorOpen = any([cp.vl["BodyInfo_3_FD1"]["DrStatDrv_B_Actl"], cp.vl["BodyInfo_3_FD1"]["DrStatPsngr_B_Actl"],
                        cp.vl["BodyInfo_3_FD1"]["DrStatRl_B_Actl"], cp.vl["BodyInfo_3_FD1"]["DrStatRr_B_Actl"]])
    ret.seatbeltUnlatched = cp.vl["RCMStatusMessage2_FD1"]["FirstRowBuckleDriver"] == 2

    # blindspot sensors
    if self.CP.enableBsm:
      cp_bsm = cp_cam if self.CP.flags & FordFlags.CANFD else cp
      ret.leftBlindspot = cp_bsm.vl["Side_Detect_L_Stat"]["SodDetctLeft_D_Stat"] != 0
      ret.rightBlindspot = cp_bsm.vl["Side_Detect_R_Stat"]["SodDetctRight_D_Stat"] != 0

    self.lkas_enabled = bool(cp.vl["Steering_Data_FD1"]["TjaButtnOnOffPress"])

    # Stock steering buttons so that we can passthru blinkers etc.
    self.buttons_stock_values = cp.vl["Steering_Data_FD1"]
    # Stock values from IPMA so that we can retain some stock functionality
    self.acc_tja_status_stock_values = cp_cam.vl["ACCDATA_3"]
    self.lkas_status_stock_values = cp_cam.vl["IPMA_Data"]

    return ret

  def update_traffic_signals(self, cp_cam):
    # TODO: Check if CAN platforms have the same signals
    if self.CP.flags & FordFlags.CANFD:
      self.v_limit = cp_cam.vl["Traffic_RecognitnData"]["TsrVLim1MsgTxt_D_Rq"]
      v_limit_unit = cp_cam.vl["Traffic_RecognitnData"]["TsrVlUnitMsgTxt_D_Rq"]

      speed_factor = CV.MPH_TO_MS if v_limit_unit == 2 else CV.KPH_TO_MS if v_limit_unit == 1 else 0

      return self.v_limit * speed_factor if self.v_limit not in (0, 255) else 0

  @staticmethod
  def get_can_parser(CP):
    messages = [
      # sig_address, frequency
      ("VehicleOperatingModes", 100),
      ("BrakeSysFeatures", 50),
      ("Yaw_Data_FD1", 100),
      ("DesiredTorqBrk", 50),
      ("EngVehicleSpThrottle", 100),
      ("EngVehicleSpThrottle2", 50),
      ("BrakeSnData_4", 50),
      ("EngBrakeData", 10),
      ("Cluster_Info1_FD1", 10),
      ("EPAS_INFO", 50),
      ("Steering_Data_FD1", 10),
      ("BodyInfo_3_FD1", 2),
      ("RCMStatusMessage2_FD1", 10),
    ]

    if CP.flags & FordFlags.ALT_STEER_ANGLE:
      messages += [
        ("SteeringPinion_Data_Alt", 100),
        ("ParkAid_Data", 50),
        ("TransGearData",10),
      ]
    else:
      messages += [
        ("SteeringPinion_Data", 100),
      ]
      if CP.transmissionType == TransmissionType.automatic:
        messages += [
          ("PowertrainData_10",10)
        ]
    if CP.flags & FordFlags.CANFD:
      messages += [
        ("Lane_Assist_Data3_FD1", 33),
        ("Cluster_Info_3_FD1", 10),
      ]
    else:
      messages += [
        ("INSTRUMENT_PANEL", 1),
      ]

    if CP.transmissionType == TransmissionType.automatic:
      messages += [
        ("Gear_Shift_by_Wire_FD1", 10),
      ]
    elif CP.transmissionType == TransmissionType.manual:
      messages += [
        ("Engine_Clutch_Data", 33),
        ("BCM_Lamp_Stat_FD1", 1),
      ]

    if CP.enableBsm and not (CP.flags & FordFlags.CANFD):
      messages += [
        ("Side_Detect_L_Stat", 5),
        ("Side_Detect_R_Stat", 5),
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, CanBus(CP).main)

  @staticmethod
  def get_cam_can_parser(CP):
    messages = [
      # sig_address, frequency
      ("ACCDATA", 50),
      ("ACCDATA_2", 50),
      ("ACCDATA_3", 5),
      ("IPMA_Data", 1),
    ]

    if CP.flags & FordFlags.CANFD:
      messages += [
        ("Traffic_RecognitnData", 1),
      ]

    if CP.enableBsm and CP.flags & FordFlags.CANFD:
      messages += [
        ("Side_Detect_L_Stat", 5),
        ("Side_Detect_R_Stat", 5),
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, CanBus(CP).camera)
