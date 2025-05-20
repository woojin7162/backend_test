from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
import requests


MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["Cluster0"]  # 실제 DB 이름으로 변경
collection = db["scheduled_messages"]


app = Flask(__name__)
CORS(app)



def save_scheduled_message(run_time, content):
    now = datetime.utcnow() + timedelta(hours=9)
    if run_time < now:
        print(f"[예약 무시] 이미 지난 시간({run_time})의 메시지는 저장하지 않습니다.")
        return
    collection.insert_one({"content": content, "run_time": run_time})

def send_discord_message(content):
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
    if not DISCORD_WEBHOOK_URL:
        print("웹훅 URL이 설정되지 않았습니다.")
        return None
    payload = {
        "content": content,
        "username": "교대근무 알리미"
    }
    try:
        url = DISCORD_WEBHOOK_URL
        if "?wait=true" not in url:
            url += "?wait=true"
        resp = requests.post(url, json=payload, timeout=5)
        print("웹훅 응답:", resp.status_code, resp.text)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")  # 메시지 ID 반환
    except Exception as e:
        print("웹훅 전송 오류:", e)
    return None

@app.route('/current_status', methods=['GET'])
def current_status():
    latest = collection.find_one(sort=[('sent_at', -1)])
    if latest:
        if '_id' in latest:
            latest['_id'] = str(latest['_id'])
        # outputInfo 생성
        shift_type = latest.get('shiftType')
        shift_order = latest.get('shiftOrder')
        shift_time_range = latest.get('shiftTimeRange')
        task_type = latest.get('taskType')
        morning_times = latest.get('morningTimes', [])

        info_map = {
            "morning": "오전근무",
            "afternoon": "오후근무",
            "recycling": "분리수거",
            "cleaning": "화장실청소"
        }

        if shift_type == "afternoon":
            output_info = f"{info_map.get(shift_type, shift_type)}, 순번 {shift_order}, 시간대 {shift_time_range}"
            if shift_order in ['1', '3']:
                output_info += f", 추가 작업: {info_map.get(task_type, task_type)}"
        else:
            if morning_times:
                times_str = ", ".join([f"{int(t) if int(t) <= 12 else int(t)-12}시" for t in morning_times])
                output_info = f"{info_map.get(shift_type, shift_type)}<br>선택한 교대시간 : {times_str}"
            else:
                output_info = f"{info_map.get(shift_type, shift_type)}<br>선택한 교대시간 없음"

        latest['outputInfo'] = output_info
        return jsonify(latest)
    else:
        return jsonify({})



@app.route('/clear_schedules', methods=['POST'])
def clear_schedules():
    # 디스코드 메시지 삭제
    # DB 비우기
    collection.delete_many({})
    return jsonify({'status': 'success', 'message': '모든 예약 및 디스코드 메시지가 삭제되었습니다.'})

@app.route('/', methods=['POST', 'OPTIONS'])
def handle_shift():
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "POST,OPTIONS")
        return response

    data = request.get_json()
    required = ['shiftType', 'shiftOrder', 'shiftTimeRange', 'taskType']
    if not all(k in data for k in required):
        return jsonify({'status': 'error', 'message': '필수 데이터 누락'}), 400

    now = datetime.utcnow() + timedelta(hours=9)  # 한국시간, 워커도 동일하게 맞춰야 함
    shift_type = data['shiftType']
    shift_order = data['shiftOrder']
    shift_time_range = data['shiftTimeRange']
    task_type = data['taskType']

    info_map = {
        "morning": "오전근무",
        "afternoon": "오후근무",
        "recycling": "분리수거",
        "cleaning": "화장실청소"
    }

    # 근무 접수 메시지 예약 (즉시)
    if shift_type == "afternoon":
        if shift_order == "2":
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 순번: {shift_order}\n"
                f"- 시간대: {shift_time_range}"
            )
        else:
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 순번: {shift_order}\n"
                f"- 시간대: {shift_time_range}\n"
                f"- 추가작업: {info_map.get(task_type, task_type)}"
            )
    else:
        morning_times = data.get("morningTimes", [])
        if morning_times:
            times_str = ", ".join([f"{int(t) if int(t) <= 12 else int(t)-12}시" for t in morning_times])
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 선택한 교대시간: {times_str}"
            )
        else:
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 선택한 교대시간 없음"
            )
    # 즉시 메시지 예약
    # 즉시 메시지 전송
    message_id = send_discord_message(msg)
    if message_id:
        collection.insert_one({
            "discord_message_id": message_id,
            "sent_at": datetime.utcnow() + timedelta(hours=9),
            "shiftType": shift_type,
            "shiftOrder": shift_order,
            "shiftTimeRange": shift_time_range,
            "taskType": task_type,
            "morningTimes": data.get("morningTimes", [])
    })



    # 삭제 예약 시간 계산
    delete_time = None
    if shift_type == "morning":
        delete_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    elif shift_type == "afternoon":
        delete_time = now.replace(hour=0, minute=55, second=0, microsecond=0)
    if delete_time and delete_time > datetime.utcnow():
        save_scheduled_message(delete_time, "[삭제] " + msg)

    # 교대 알림 예약
    if shift_type == "morning":
        morning_times = data.get("morningTimes", [])
        for t in morning_times:
            try:
                hour = int(t)
            except ValueError:
                continue
            start_alarm = now.replace(hour=hour-1, minute=54, second=0, microsecond=0)
            end_alarm = now.replace(hour=hour, minute=54, second=0, microsecond=0)
            save_scheduled_message(start_alarm, "포스 시작 교대 시간입니다!")
            save_scheduled_message(end_alarm, "포스 종료 교대 시간입니다! 주차장을 확인해주세요!")

    if shift_type == 'afternoon':
        order_times = {
            '1': [(16, 17), (19, 20)],
            '2': [(17, 18), (20, 21)],
            '3': [(18, 19), (21, 22)]
        }
        for start_hour, end_hour in order_times.get(shift_order, []):
            start_alarm = now.replace(hour=start_hour-1, minute=54, second=0, microsecond=0)
            end_alarm = now.replace(hour=end_hour-1, minute=54, second=0, microsecond=0)
            save_scheduled_message(start_alarm, f"포스 시작 교대 시간입니다! (순번 {shift_order})번")
            save_scheduled_message(end_alarm, f"포스 종료 교대 시간입니다! 주차장을 확인해주세요! (순번 {shift_order})")
        if shift_time_range == '2-4':
            times = [
                (1, 13, 55, 14, 35),
                (2, 14, 35, 15, 15),
                (3, 15, 15, 15, 55)
            ]
        else:
            times = [
                (1, 14, 55, 15, 15),
                (2, 15, 15, 15, 35),
                (3, 15, 35, 15, 55)
            ]
        for num, sh, sm, eh, em in times:
            if str(num) == shift_order:
                start = now.replace(hour=sh, minute=sm-1, second=0, microsecond=0)
                end = now.replace(hour=eh, minute=em-1, second=0, microsecond=0)
                save_scheduled_message(start, f"포스 시작 교대 시간입니다! ({sh}:{sm:02d}, 순번 {num})")
                save_scheduled_message(end, f"포스 종료 교대 시간입니다! ({eh}:{em:02d}, 순번 {num})")

    if shift_order != '2':
        if task_type == 'recycling':
            t = now.replace(hour=20, minute=0, second=0, microsecond=0)
            save_scheduled_message(t, "분리수거 시간입니다!")
        elif task_type == 'cleaning':
            t = now.replace(hour=20, minute=30, second=0, microsecond=0)
            save_scheduled_message(t, "화장실청소 시간입니다!")

    leave_alarm = now.replace(hour=22, minute=0, second=0, microsecond=0)
    save_scheduled_message(leave_alarm, "퇴근! 수고하셨습니다!")

    print("받은 데이터:", data)
    return jsonify({
        'status': 'success',
        'message': '근무 정보가 정상적으로 접수되고 알림이 예약되었습니다.',
        'data': data
    }), 200

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'status': 'ok',
        'message': '교대근무 알리미 백엔드가 실행 중입니다.'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)


    
