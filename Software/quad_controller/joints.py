""" Module to handle moving the robot joint, either real or simulated.

This module assumes some conventions and a specific method of installation and calibration.

1)  The robot's zero point for each joint is when th shoulders are level and the legs are
pointing straight down.

2) To install a servo, first use a servo tester or software to command the servo
to it's mid-point.  This means to a 1500 uSec pulse length.

3) Find the mid-point of travel in the robot's joint.  Doing this by eye is good enough'

4) install the still centered servo so the joint is in its midrange of motion.  Each
spline groove on the servo is a few degree apart, so you can not get this perfect.
Get this as close as you can by eye.

5) the next step is to measure and calibrate so we can compensate for inevitable error
in the above process.  So use the test software to commend the joint to it's "zero
point" where the leg is straight.  Record the setting you had to use to "zero"
the joint.  This setting should be very close to the servo's mid-point.  Write it down.

6) command the servo to go to the lowest joint angle.   Note that this might require
a higher servo angle.  Servos can be installed to run "backward" or forward and
this depends on how the output shaft is facing relative to the robot.
So, run the servo until it either causes the robot's joint to het a stop and jam.
or until the servo motor has reach a limit.  Then back off a degree or two.
this is the lower limit of rotation.  Write this number down.

7) do the same in the other direction to find the upper imit of rotation.  It does
not matter why the limit is reach.  either the robot self-colides of the servo
runs out of range of motion.  Write this number down.

8) assemble all the servos using this method. then enter the data you collected
in the table below, that is three numbers for each servo.  (Eventually I will write
an automated tol to do this and we can store the numbers in a JSON file and
not have to write won number and edit ths Python file.)
"""

import math
import logging
log = logging.getLogger(__name__)

import config

if config.GotHardware:
    from adafruit_servokit import ServoKit

if config.ui_web_gui:
    import PySimpleGUIWeb as sg
elif config.ui_x11_gui:
    import PySimpleGUI as sg

class ServoShim:
    """Class to add a thin layer over the physical servo motors.

    The layer adds some features
    1) the servos might be not used at all. This allows testing on computers
       that don't have the hardware to drive servos
    2) The joint angle is mapped to the servo angle
    3) logging of commands for post analysis
    4) realtime performance capture
    5) Joint and servo limits are enforced

    This is intened to be a light weight class where all real-time functions
    have very low latency
    
    TBD:  Should think about driving the PCA9685 chip using uSec rether then
    letting Servo Kit convert degrees to uSec.   This way we can convert
    directly from redians to uSec and apply a per-servo calibration all at
    the same time.   See https://learn.adafruit.com/adafruit-16-channel-servo-driver-with-raspberry-pi/library-reference
    """

    def __init__(self):
        """Class constructor, builds calibration and limits tables for quick lookup

        Parameters:
            have_hardware:  overides config if set True, used for unit tests
                            when it is hard to change config.  Should not be
                            set outside a test environment.

        """

        # TABLE OF USER MEASURED VALUES
        #
        # the table below should be filled with data measured by the
        # method descried above.   The units are degrees in a
        # right-handed system.
        #
        # the table contains 16 tuples, 12 are used, four positions are not
        # used.  Each tuple contains the following, in degrees:
        # (zero_point, lower_limit, upper_limit) where
        #   zero_point -  when the servo is commanded to this value the leg is at
        #                 zero, which by convention is straight down and level
        #   lower_limit - when the servo is commanded to thi value the joint is
        #                 very near the point where it will physically stall out.
        #                 Note this value might is high if the servo is installed
        #                 to run in the reverse direction.  Some will be.
        #   upper_limit - As above but the joint is near the upper limit when the
        #                 servo is set to this value
        #
        self.servo_measurements = (
            # Joint1,           Joint2,             Joint3,             unused
            (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (0, 0, 0),  # Front Left
            (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (0, 0, 0),  # Front Right
            (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (0, 0, 0),  # Rear Left
            (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (90.0, 0.0, 180.0), (0, 0, 0))  # Rear Right

        # This table is ued to convert radians to degrees while at the same time
        # correcting for the servo' install rotation direction.
        r2d_list = []
        for (_, lower, upper) in self.servo_measurements:
            if lower < upper:
                r2d = 180.0 / math.pi
            elif lower > upper:
                r2d = -180.0 / math.pi
            else:
                r2d = 0.0
            r2d_list.append(r2d)
        # Tuples are faster to index, and we do this amost 1000 times per second.
        # So it makes some sense to convert the list to a tuple.
        self.rad2deg_direction = tuple(r2d_list)
        
        """
        This table records the measured limits for each servo.  They are all
        different, and should be measured before they are installed.  The table
        is a list of tuples tuples with these feilds:
        (minimum microseconds, maximum microseconds, degrees of movement)
        """
        self.servo_range = (
            # Front Left
            (500, 2500, 180.0),     # Shoulder
            (500, 2500, 180.0),     # upper
            (500, 2500, 180.0),     # lower
            (1,2,3),                # not used

            # Front Right
            (500, 2500, 180.0),     # Shoulder
            (500, 2500, 180.0),     # upper
            (500, 2500, 180.0),     # lower
            (1,2,3),                # not used

            # Rear Left
            (500, 2500, 180.0),     # Shoulder
            (500, 2500, 180.0),     # upper
            (500, 2500, 180.0),     # lower
            (1,2,3),                # not used

            # Rear Right
            (500, 2500, 180.0),     # Shoulder
            (500, 2500, 180.0),     # upper
            (500, 2500, 180.0),     # lower
            (1,2,3),                # not used
        )
        
        # Set this depending on the servo specs.   Cheap servos use 50Hz
        # better servos ue 300+ Hz
        pwm_freq = 300

        if config.GotHardware:
            self.kit = ServoKit(channels=16, 
                                frequency=pwm_freq,
                                reference_clock_speed=25000000)
            
            for chan in range(16):
                self.kit.servo[chan].set_pulse_width_range(
                    min_pulse=self.servo_range[chan][0],
                    max_pulse=self.servo_range[chan][1])
                self.kit.servo[chan].actuation_range = self.servo_range[chan][2]


    def set_angle(self, channel_number: int, radians: float) -> None:
        """Set servo to specified joint angle

        Several things are done here
            1) radians converted to degrees
            2) the joint's rotational limit is checked and will not be moved past this.
            3) check if real hardware is present either move the servo or write to a log.
        """

        # converts to degrees and for servo installed direction at the same time
        joint_degrees = radians * self.rad2deg_direction[channel_number]
        servo_zero_point, low_limit, high_limit = self.servo_measurements[channel_number]
        servo_degrees = joint_degrees + servo_zero_point

        # enforce rotation limit
        if servo_degrees < low_limit:
            log.warning('clipping channel {0} from {1:7.2} to {2:7.2}'.format(
                channel_number, servo_degrees, low_limit))
            servo_degrees = low_limit

        elif servo_degrees > high_limit:
            log.warning('clipping channel {0} from {1:7.2} to {2:7.2}'.format(
                channel_number, servo_degrees, high_limit))
            servo_degrees = high_limit

        if config.GotHardware:
            self.kit.servo[channel_number].angle = servo_degrees

        log.debug('set_servo channel {0}, angle = {1:7.2f}'.format(
            channel_number, servo_degrees))
        return

    def set_raw_degrees(self, channel_number: int, degrees: float) -> None:
        """
        Returns:Set the specifid servo to a value in degrees with not limit check or calibration

        Args:
            channel_number: An integer in the range 0..15 that is passed to servokit
            degrees:        The angle that the servo is to go to, passed
                            unchanged to the servo

        Returns:   None.

        This function should only be called during off-line calibration, not real-time,
        so it is OK to let it crash if the parameters are out of range
        """

        assert 0 <= channel_number <= 15, 'channel number is out of range'
        assert 0.0 <= degrees <= 360.0, 'angle is out of range'

        self.kit.servo[channel_number].angle = degrees
        return

def run_test_gui():
    if config.GotHardware:
        ssh = ServoShim()

    layout = [  [sg.Text('Channel 1..15', size=(25,1)),
                        sg.Input(enable_events=True, size=10, key='-CH-')],

                [sg.Text('Servo, degrees 0..360', size=(25,1)),
                        sg.Input(enable_events=True, size=10,  key='-SD-'),
                        sg.Button('Move Servo', size=10, key='-MS-')],

                [sg.Text('Joint, radian -2pr..2pi', size=(25,1)),
                        sg.Input(enable_events=True, size=10,  key='-JR-'),
                        sg.Button('Move Joint', size=10,  key='-MJ-')],

                [sg.Button('Exit')]
             ]

    if config.ui_web_gui:
        window = sg.Window('Servo Test and Setup', layout, web_port=2222, web_start_browser=False)
    elif config.ui_x11_gui:
        window = sg.Window('Servo Test and Setup', layout)

    while True:  # Event Loop
        event, values = window.read()

        if event in (None, 'Exit'):
            break

        if event == '-CH-':
            if values['-CH-'] != '':
                try:
                    channel_number = int(values['-CH-'])
                except ValueError:
                    sg.popup('Channel number invalid')
                    window['-CH-'].update('')
                else:
                    if channel_number > 15 or channel_number < 0:
                        sg.popup('Channel number is out of range')
                        window['-CH-'].update('')

        if event == '-SD-':
            if values['-SD-'] not in ('', '.'):
                try:
                    raw_degrees = float(values['-SD-'])
                except ValueError:
                    sg.popup('angle invalid')
                    window['-SD-'].update('')
                else:
                    if raw_degrees > 360. or raw_degrees < 0.:
                        sg.popup('angle out of range, 0..360')
                        window['-SD-'].update('')

        if event == '-JR-':
            if values['-JR-'] not in ('', '-', '.'):
                try:
                    joint_radians = float(values['-JR-'])
                except ValueError:
                    sg.popup('angle invalid')
                    window['-JR-'].update('')
                else:
                    limit = 2.0 * math.pi
                    if joint_radians > limit or joint_radians < -limit:
                        sg.popup('angle out of range, -2pi..2pi')
                        window['-JR-'].update('')

        if event == '-MS-':
            if config.GotHardware:
                ssh.set_raw_degrees(channel_number, raw_degrees)
            else:
                sg.popup('no hardware\n(ch={0}, degrees={1:7.2f})'.format(
                        channel_number, raw_degrees))

        if event == '-MJ-':
            if config.GotHardware:
                ssh.set_angle(channel_number, joint_radians)
            else:
                sg.popup('no hardware\n(ch={0}, radians={1:7.2f})'.format(
                        channel_number, joint_radians))

    window.close()
    return


if __name__ == "__main__":
    logging.basicConfig(filename='quad_controller.log',
                        filemode='w',
                        level=logging.DEBUG, )

    run_test_gui()
