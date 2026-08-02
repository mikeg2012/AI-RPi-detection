import time, os, logging
from datetime import datetime
import base64
import cv2
import numpy as np
from dotenv import load_dotenv
import resend
import interesting_list
from exif import Image as ExifImage
import sys
import simplematrixbotlib as botlib
import asyncio
import mimetypes
import io
import torch
from torchvision import models

if sys.platform == "win32":
    from PIL import Image
else:
    import RPi.GPIO as GPIO
    import motor
    from picamera2 import Picamera2

# загружаем содержимое .env файла
load_dotenv()

USE_LOCAL_MODEL = os.environ.get("USE_LOCAL_MODEL", "False").lower() == "true"
print(f"USE_LOCAL_MODEL: {USE_LOCAL_MODEL}")

matrix_url = os.environ.get("URL")
bot_name = os.environ.get("BOT")
bot_password = os.environ.get("BOT_PASS")
room_id = os.environ.get("ROOM_ID")

# учетные данные
creds = botlib.Creds(matrix_url, bot_name,bot_password)

# задаем константы
PREFIX = "!"
CAT_FEED_AMOUNT1 = 256
CAT_FEED_AMOUNT2 = 512
CAT_FEED_AMOUNT3 = 768
CAT_FEED_AMOUNT4 = 1024

# загружаем список животных
interesting_array = interesting_list.animals

# инициализация бота
bot = botlib.Bot(creds)
# глобальная переменная для модели
model = None
weights = None
preprocess = None
model_input_size = 640, 480


async def init_local_model():
    global model, weights, preprocess
    start_time = time.time()
    # Load the model and libraries if we're using it
    print(torch.backends.quantized.supported_engines)
    #    torch.backends.quantized.engine = 'qnnpack'
    torch.backends.quantized.engine = 'onednn'

    # Загрузка в память и подготовка весов модели
    weights = models.Swin_V2_S_Weights.DEFAULT
    preprocess = weights.transforms()
    model = models.swin_v2_s(weights=weights)
    model.eval()

    # Время завершения загрузки модели
    end_time = time.time()
    execution_time = end_time - start_time
    # вывод времени загрузки модели
    print(f"Loaded local model to memory in {execution_time} seconds")


logging.basicConfig(level=logging.INFO) 
#llm = ChatOpenAI(model="gpt-4-vision-preview", max_tokens=500)
global base, static
base = os.environ.get("TMP_FILE_BASE_PATH", "tmp")
static = os.environ.get("TMP_FILE_STATIC_PATH", "static")

if sys.platform == "win32":
    save_dir = os.path.join('c:', os.sep, base, static)
    static_save_dir = os.path.join('c:', os.sep, base)
else:
    save_dir = os.path.join(os.sep, base, static)
    static_save_dir = os.path.join(os.sep, base)

USE_ELEVEN = False
os.makedirs(save_dir, exist_ok=True)
resend.api_key = os.environ.get("RESEND_API_KEY")
requestPrompt = os.environ.get("REQUEST_PROMPT")
lastEmailTs = None

print(f"USE_ELEVEN: {USE_ELEVEN}")

if sys.platform == "win32":
    cam = cv2.VideoCapture(1)
    if not cam.isOpened():
        print("Error: Could not open camera.")
        exit()
else:
    picam2 = Picamera2()
    picam2.start()

time.sleep(2)

# обработчик сообщений
@bot.listener.on_message_event
async def echo(room, message):
    match = botlib.MessageMatch(room, message, bot, PREFIX)

    if match.is_not_from_this_bot() and match.prefix() and match.command("echo"):
        response = " ".join(arg for arg in match.args())
        await bot.api.send_text_message(room.room_id, f'Вы сказали: {response}')


async def send_image_message(bot, room_id, image_path):
    """
    Загружает локальное изображение на сервер Matrix и отправляет его в чат.
    """
    if not os.path.exists(image_path):
        print(f"Ошибка: Файл {image_path} не найден.")
        return

    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/jpeg"

    with Image.open(image_path) as img:
        width, height = img.size

    # Читаем файл
    with open(image_path, "rb") as f:
        image_data = f.read()
        file_size = len(image_data)

    # ИСПРАВЛЕНИЕ: Оборачиваем байты в BytesIO, чтобы nio мог их прочитать
    data_stream = io.BytesIO(image_data)

    # Загружаем поток данных на медиа-сервер Matrix
    response = await bot.api.async_client.upload(
        data_stream,  # Передаем поток, а не bytes!
        content_type=mime_type,
        filename=os.path.basename(image_path)
    )

    # 1. Если пришел кортеж (Response, Error), берем первый элемент
    if isinstance(response, tuple):
        response = response[0]

    # 2. Пытаемся достать mxc:// ссылку разными способами (из объекта или из словаря)
    if hasattr(response, "content_uri") and response.content_uri:
        mxc_url = response.content_uri
    elif isinstance(response, dict) and "content_uri" in response:
        mxc_url = response["content_uri"]
    # Резервный вариант на случай, если библиотека вернула сырой JSON-ответ
    elif hasattr(response, "transport_response") and hasattr(response.transport_response, "json"):
        try:
            # Попробуем асинхронно или синхронно прочитать json, если это возможно
            json_data = response.json() if not asyncio.iscoroutinefunction(response.json) else await response.json()
            mxc_url = json_data.get("content_uri")
        except Exception:
            mxc_url = None
    else:
        mxc_url = None

    # Если ссылку найти так и не удалось, выводим ошибку
    if not mxc_url:
        print(f"Ошибка: Не удалось извлечь content_uri из ответа: {response}")
        return


    content = {
        "body": os.path.basename(image_path),
        "info": {
            "size": file_size,
            "mimetype": mime_type,
            "w": width,
            "h": height
        },
        "msgtype": "m.image",
        "url": mxc_url
    }

    await bot.api.async_client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content
    )
    print(f"Картинка {image_path} успешно отправлена!")


async def main():
    # Запускаем основной код и фоновую синхронизацию бота одновременно
    await asyncio.gather(
        main_logic(),
        bot.main()
    )


async def main_logic():
    if sys.platform == "win32":
        print("win32 platform detected")
        print(f"{sys.platform} platform detected")
    else:
        init_gpio()
        motor.feed_cat(GPIO, CAT_FEED_AMOUNT1)
        print(f"{sys.platform} platform detected")

    await bot.api.login()
    print("Основной код запущен!")

    # загрузка локальной модели
    if USE_LOCAL_MODEL:
        print(f"Loading local model to memory")
        await init_local_model()

    #    base64Frames = []
#    numOfFrames = 5
#    availableFunctions = {"send_email": send_email}
#    global lastEmailTs
    captureMode = False

    while True:
        filePath, image = take_photo(save_dir)

        if not captureMode:
            interestingBool, objects_detected = is_interesting(image, filePath)
            if interestingBool:
                # найдено что-то интересное
#                captureMode = True
                print(f"Interesting image detected:\n {objects_detected}")

                try:
                    print("Попытка отправки уведомления...")

#                    await bot.api.send_text_message(ROOM_ID, objects_detected)

                    await send_image_message(bot, room_id, filePath)

                    print("Сообщение успешно отправлено в чат!")
                except Exception as e:
                    print(f"Не удалось отправить сообщение: {e}")

                print("Make pause..")
                time.sleep(5)
            else:
                # нет интересной картинки
                print("Nothing interesting")
                notification_text = "⚠️ Nothing interesting."
                try:
                    # Отправляем сообщение в конкретную комнату
                    await bot.api.send_text_message(room_id, notification_text)
                    print("Уведомление успешно отправлено.")
                except Exception as e:
                    print(f"Ошибка при отправке уведомления: {e}")

                print("Make pause..")
                time.sleep(5)

                print("continue...")
                os.remove(filePath)
                continue

#        base64_image = encode_image(filePath)
#        if len(base64Frames) < numOfFrames:
#            base64Frames.append(base64_image)
#        else:
#            # We got enough frames, let's process them
#            captureMode = False
#            collageFilePath = save_image_collage(base64Frames, static_save_dir)
#            base64Frames = []

#        time.sleep(2)

    # Cleanup
#    GPIO.cleanup()

# Функция инициализации GPIO
def init_gpio():
    # Use BCM GPIO references
    GPIO.setmode(GPIO.BCM)

    # Set pins as output
    for pin in motor.ControlPin:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, False)
    return GPIO

#def describe_image(collageFilePath):
#    base64 = encode_image(collageFilePath)
#    result = llm_with_tools.invoke(
#        [HumanMessage(
#            content = [
#                 {"type": "text", "text": requestPrompt},
#                 {"type": "image_url",
#                  "image_url":
#                    {"url": f"data:image/jpeg;base64,{base64}"
#                    }
#                }
#        ])]
#    )
#    print('langchain result: ', result)
#    return result

#def encode_image(image_path):
#    while True:
#        try:
#            with open(image_path, "rb") as image_file:
#                return base64.b64encode(image_file.read()).decode("utf-8")
#        except IOError as e:
#            if e.errno != errno.EACCES:
#                # Not a "file in use" error, re-raise
#                raise
#            # File is being written to, wait a bit and retry
#            time.sleep(0.1)

# image from PIL
def is_interesting(image, filePath):
    # Everything is interesting if we're not using the model
    if not USE_LOCAL_MODEL:
        return True, "Everything is awesome"

    if sys.platform == "win32":
        if isinstance(image, np.ndarray):
            model_image = Image.fromarray(image)
        else:
            model_image = image.copy()
        model_image = model_image.resize(model_input_size).convert('RGB')
    else:
        model_image = image.resize(model_input_size).convert('RGB')

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

def take_photo(save_dir):
    if sys.platform == "win32":
        print("Making photo...")
    else:
        global picam2
        print("Making photo...")

    try:
        timestamp = int(datetime.timestamp(datetime.now()))
        image_name = f'{timestamp}.jpg'
        filepath = os.path.join(save_dir, image_name)

        if sys.platform == "win32":
            ret, image = cam.read()
            if not ret:
                print("Error: Failed to grab frame.")
                return '', ''
            cv2.imwrite(filepath, image)
            print(f"Image saved as {filepath}")
        else:
            request = picam2.capture_request()
            image = request.make_image("main")

            # request.save("main", filepath)
            image.save(filepath)

            request.release()
            logging.info(f"Image captured successfully. Path: {filepath}")
        return filepath, image
    except Exception as e:
        logging.error(f"Error capturing image: {e}")

def save_image_collage(base64_images, static_save_dir):
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
    file_path = os.path.join(static_save_dir, f"montage_{timestamp}.jpg")
    cv2.imwrite(file_path, montage)
    logging.info(f"Montage saved successfully. Path: {file_path}")
    return file_path

if __name__ == "__main__":
    asyncio.run(main())

    if sys.platform == "win32":
        cam.release()
        cv2.destroyAllWindows()
    else:
        model_image = image.resize(model_input_size).convert('RGB')



