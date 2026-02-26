# from picamera2 import Picamera2
import time, os, logging, getpass
from datetime import datetime
import base64
import cv2
import numpy as np
#from elevenlabs import play, save, voices
#from elevenlabs.client import ElevenLabs # new line
from dotenv import load_dotenv
import resend
import json
import interesting_list
from exif import Image as ExifImage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import RPi.GPIO as GPIO
import time
import motor

load_dotenv()

USE_LOCAL_MODEL = os.environ.get("USE_LOCAL_MODEL", "False").lower() == "true"
print(f"USE_LOCAL_MODEL: {USE_LOCAL_MODEL}")
if USE_LOCAL_MODEL: 
    print(f"Loading local model to memory")
    # Start the timer
    start_time = time.time()
    # Load the model and libraries if we're using it
    import torch
    from torchvision import models
    print(torch.backends.quantized.supported_engines)
#    torch.backends.quantized.engine = 'qnnpack'
    torch.backends.quantized.engine = 'onednn'

    # Load model into memory and prep weights
    weights = models.Swin_V2_S_Weights.DEFAULT
    preprocess = weights.transforms()
    model = models.swin_v2_s(weights=weights)
    model.eval()
    model_input_size = 640, 480

    # End the timer
    end_time = time.time()
    execution_time = end_time - start_time
    print(f"Loaded local model to memory in {execution_time} seconds")

interesting_array = interesting_list.animals

logging.basicConfig(level=logging.INFO) 
llm = ChatOpenAI(model="gpt-4-vision-preview", max_tokens=500)
save_location = os.environ.get("TMP_FILE_PATH", 'static')
save_base_path = os.environ.get("TMP_FILE_BASE_PATH", "/tmp")
save_dir = os.path.join(save_base_path, save_location)
USE_ELEVEN = False
os.makedirs(save_dir, exist_ok=True)
resend.api_key = os.environ.get("RESEND_API_KEY")
print(f"USE_ELEVEN: {USE_ELEVEN}")

cam = cv2.VideoCapture(0)
if not cam.isOpened():
    print("Error: Could not open camera.")
    exit()


#picam2 = Picamera2()
#picam2.start()
time.sleep(2)
requestPrompt = os.environ.get("REQUEST_PROMPT")
lastEmailTs = None

def main():
    init_gpio()
    motor.feed_cat(GPIO)
    exit()

    base64Frames = []
    numOfFrames = 5
#    availableFunctions = {"send_email": send_email}
    global lastEmailTs
    captureMode = False

    while True:
        filePath, image = take_photo()

        if not captureMode:
            interestingBool, objects_detected = is_interesting(image, filePath)
            if interestingBool:
                captureMode = True
                print(f"Interesting image detected:\n {objects_detected}")
            else:
                print("Not interesting")
                continue

        base64_image = encode_image(filePath)
        if len(base64Frames) < numOfFrames:
            base64Frames.append(base64_image)
        else:
            # We got enough frames, let's process them
            captureMode = False
            collageFilePath = save_image_collage(base64Frames)
            base64Frames = []

        time.sleep(2)

    # Cleanup
    GPIO.cleanup()

# Функция инициализации GPIO
def init_gpio():
    # Use BCM GPIO references
    GPIO.setmode(GPIO.BCM)

    # Set pins as output
    for pin in motor.ControlPin:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, False)
    return GPIO



def describe_image(collageFilePath):
    base64 = encode_image(collageFilePath)
    result = llm_with_tools.invoke(
        [HumanMessage(
            content = [
                 {"type": "text", "text": requestPrompt},
                 {"type": "image_url", 
                  "image_url": 
                    {"url": f"data:image/jpeg;base64,{base64}"
                    }
                }
        ])]
    )
    print('langchain result: ', result)
    return result

def encode_image(image_path):
    while True:
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except IOError as e:
            if e.errno != errno.EACCES:
                # Not a "file in use" error, re-raise
                raise
            # File is being written to, wait a bit and retry
            time.sleep(0.1)

# image from PIL
def is_interesting(image, filePath):
    # Everything is interesting if we're not using the model
    if not USE_LOCAL_MODEL:
        return True, "Everything is awesome"
#    model_image = image.resize(model_input_size).convert('RGB')

    model_image = image.copy().resize(model_input_size).convert('RGB')

    # preprocess
    input_tensor = preprocess(model_image)

    # create a mini-batch as expected by the model
    input_batch = input_tensor.unsqueeze(0)

    # output = net(input_batch)
    prediction = model(input_batch)

    top = list(enumerate(prediction[0].softmax(dim=0)))    
    top.sort(key=lambda x: x[1], reverse=True)

    result = ""
    top_categories = []
    for idx, val in top[:10]:
        result_str = f"{val.item()*100:.2f}% {weights.meta['categories'][idx]}"
        top_categories.append(weights.meta['categories'][idx])
        result = result + (result_str + "\n")
        print(result_str)

    with open(filePath, "rb") as saved_image:
        exif_image = ExifImage(saved_image)

    exif_image.user_comment = result

    # this cases multiple writes for 1 image, not ideal
    with open(filePath, 'wb') as new_image_file:
        new_image_file.write(exif_image.get_file())

    return any(x in interesting_array for x in top_categories), result

def take_photo():
#    global picam2
    try:
        timestamp = int(datetime.timestamp(datetime.now()))
        image_name = f'{timestamp}.jpg'
        current_dir = os.path.dirname(__file__)
        static_dir = os.path.join(current_dir, save_dir)
        filepath = os.path.join(static_dir, image_name)

        ret, image = cam.read()
        if not ret:
            print("Error: Failed to grab frame.")
            return '', ''

        file_name = "c:\\tmp\\captured_image.jpg"
        cv2.imwrite(file_name, image)
        print(f"Image saved as {file_name}")

#        config = picam2.still_configuration()
#        picam2.configure(config)
#        config = picam2.preview_configuration(main={"size": (640, 480)}, "format": "YUV420"})
#        picam2.configure(config)
#        request = picam2.capture_request()
#        image = request.make_image("main")

        # request.save("main", filepath)
#        image.save(filepath)

#        request.release()
#        logging.info(f"Image captured successfully. Path: {filepath}")

        return filepath, image
    except Exception as e:
        logging.error(f"Error capturing image: {e}")

def save_image_collage(base64_images):
    montage = None

    for base64_frame in base64_images:
        # Decode the base64 string
        jpg_original = base64.b64decode(base64_frame)

        # Convert binary data to numpy array
        jpg_as_np = np.frombuffer(jpg_original, dtype=np.uint8)

        # Decode numpy array to image
        frame = cv2.imdecode(jpg_as_np, flags=1)

        if montage is None:
            # Initialize the montage with the first frame
            montage = frame
        else:
            # Concatenate the current frame horizontally to the montage
            montage = np.hstack((montage, frame))

    # Save the montage as an image
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = os.path.join(save_dir, f"montage_{timestamp}.jpg")
    cv2.imwrite(file_path, montage)
    logging.info(f"Montage saved successfully. Path: {file_path}")
    return file_path

if __name__ == "__main__":
    main()
    cam.release()
    cv2.destroyAllWindows()
