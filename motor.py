import time

# Define GPIO pins
ControlPin = [4, 17, 27, 22]  # IN1, IN2, IN3, IN4

# 4-step sequence backward
seq_back = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1]
]

# 4-step sequence forward
seq_fw = [
    [1, 0, 0, 1],
    [0, 0, 0, 1],
    [0, 0, 1, 1],
    [0, 0, 1, 0],
    [0, 1, 1, 0],
    [0, 1, 0, 0],
    [1, 1, 0, 0],
    [1, 0, 0, 0]
]

# Function to turn motor
def setStep(GPIO, w1, w2, w3, w4):
    GPIO.output(ControlPin[0], w1)
    GPIO.output(ControlPin[1], w2)
    GPIO.output(ControlPin[2], w3)
    GPIO.output(ControlPin[3], w4)

def feed_cat(GPIO):
    # Rotate 512 steps (approx. one full revolution)
    for i in range(1024):
        for step in seq_fw:
            setStep(GPIO, step[0], step[1], step[2], step[3])
            time.sleep(0.001) # Speed control

