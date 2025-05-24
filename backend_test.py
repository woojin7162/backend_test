from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
import requests
import urllib.parse

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


def send_notilab_push(body):
    to_nickname = "Alert"  # notilab 앱 닉네임
    title = "교대근무 알리미"
    sckey = "89150194-88f3-4b84-ac93-6f9b4fa91ce9"
    url = (
        "https://asia-northeast3-noti-lab-production.cloudfunctions.net/api/notification/v1/notification?"
        f"nickname={urllib.parse.quote(to_nickname)}"
        f"&title={urllib.parse.quote(title)}"
        f"&body={urllib.parse.quote(body)}"
        f"&secretKey={urllib.parse.quote(sckey)}"
    )
    try:
        resp = requests.get(url, timeout=5)
        print("notilab 응답:", resp.status_code, resp.text)
    except Exception as e:
        print("notilab 푸시 전송 오류:", e)



@app.route('/current_status', methods=['GET'])
def current_status():
    latest = collection.find_one(sort=[('sent_at', -1)])
    if latest:
        if '_id' in latest:
            latest['_id'] = str(latest['_id'])
        # outputInfo 생성
        shift_type = latest.get('shiftType')
        shift_order = latest.get('shiftOrder')
        task_type = latest.get('taskType')
        morning_times = latest.get('morningTimes', [])
        num_people = latest.get('numPeople')
        my_order = latest.get('myOrder')
        shift_start = latest.get('shiftStart')
        shift_end = latest.get('shiftEnd')

        info_map = {
            "morning": "오전근무",
            "afternoon": "오후근무",
            "recycling": "분리수거",
            "cleaning": "화장실청소"
        }

        if shift_type == "afternoon":
            output_info = (
            f"근무유형: {info_map.get(shift_type, shift_type)}<br>"
            f"순번: {shift_order}<br>"
            )
            output_info += f"사전교대인원: {num_people or '-'}명<br>사전교대순번: {my_order or '-'}번<br>"
            if shift_start and shift_end:
                output_info += f"시간범위: {shift_start}시~{shift_end}시<br>"
            if shift_order in ['1', '3']:
                output_info += f"추가 작업: {info_map.get(task_type, task_type)}<br>"
        else:
            if morning_times:
                times_str = ", ".join([f"{int(t) if int(t) <= 12 else int(t)-12}시" for t in morning_times])
                output_info = (
                    f"{info_map.get(shift_type, shift_type)}<br>"
                    f"선택한 교대시간: {times_str}<br>"
            )
            else:
                output_info = f"{info_map.get(shift_type, shift_type)}<br>선택한 교대시간 없음<br>"
            if shift_start and shift_end:
                output_info += f"시간범위: {shift_start}시~{shift_end}시<br>"
            output_info += f"사전교대인원: {num_people or '-'}명<br>사전교대순번: {my_order or '-'}번"

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
    required = ['shiftType', 'shiftOrder', 'taskType']
    if not all(k in data for k in required):
        return jsonify({'status': 'error', 'message': '필수 데이터 누락'}), 400

    now = datetime.utcnow() + timedelta(hours=9)  # 한국시간, 워커도 동일하게 맞춰야 함
    shift_type = data['shiftType']
    shift_order = data['shiftOrder']
    task_type = data['taskType']
    shift_start = data.get("shiftStart") or None
    shift_end = data.get("shiftEnd") or None
    num_people = data.get("numPeople") or None
    my_order = data.get("myOrder") or None

    if not (shift_start and shift_end and num_people and my_order):
        return jsonify({
            'status': 'success',
            'message': '필수 교대 정보가 없어 예약 프로세스는 실행되지 않았습니다.',
            'data': data
        }), 200

    if shift_start and shift_end and num_people and my_order:
        try:
            s = int(shift_start)
            e = int(shift_end)
            n = int(num_people)
            order = int(my_order)
        except:
            return True
        if s < e:
            return jsonify({
                'status': 'error',
                'warning': '교대 알림 예약이 실패했습니다. 교대시간을 확인해주세요.',
                'data': data
            }), 200
        else:
            try:
                s = int(shift_start)
                e = int(shift_end)
                n = int(num_people)
                order = int(my_order)
                total_minutes = (e - s) * 60
                if n > 0 and order > 0 and order <= n and total_minutes > 0:
                    slot_minutes = total_minutes // n
                    start_minute = s * 60 + slot_minutes * (order - 1)
                    end_minute = s * 60 + slot_minutes * order
            # 알림 시간(시작/종료 6분 전)
                    start_alarm_minute = start_minute - 6
                    end_alarm_minute = end_minute - 6
                    start_alarm_hour = start_alarm_minute // 60
                    start_alarm_min = start_alarm_minute % 60
                    end_alarm_hour = end_alarm_minute // 60
                    end_alarm_min = end_alarm_minute % 60
                    start_alarm = now.replace(hour=start_alarm_hour, minute=start_alarm_min, second=0, microsecond=0)
                    end_alarm = now.replace(hour=end_alarm_hour, minute=end_alarm_min, second=0, microsecond=0)
                    save_scheduled_message(start_alarm, f"포스 시작 교대 시간입니다! (내 순번 {order})")
                    save_scheduled_message(end_alarm, f"포스 종료 교대 시간입니다! 주차장을 확인해주세요! (내 순번 {order})")
            except Exception as ex:
                print("shift_start~shift_end 교대 알림 예약 오류:", ex)


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
                f"- 사전교대인원: {num_people or '-'}명\n"
                f"- 사전교대순번: {my_order or '-'}번\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 순번: {shift_order}\n"
                f"- 시간범위: {shift_start}시~{shift_end}시\n" 
            )
        else:
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 사전교대인원: {num_people or '-'}명\n"
                f"- 사전교대순번: {my_order or '-'}번\n"
                f"- 순번: {shift_order}\n"
                f"- 시간범위: {shift_start}시~{shift_end}시\n"
                f"- 추가작업: {info_map.get(task_type, task_type)}\n"             
            )
    else:
        morning_times = data.get("morningTimes", [])
        if morning_times:
            times_str = ", ".join([f"{int(t) if int(t) <= 12 else int(t)-12}시" for t in morning_times])
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 사전교대인원: {num_people or '-'}명\n"
                f"- 사전교대순번: {my_order or '-'}번\n"
                f"- 시간범위: {shift_start}시~{shift_end}시\n"
                f"- 선택한 교대시간: {times_str}\n"
            )
        else:
            msg = (
                f"근무 시간 접수 완료\n"
                f"- 근무유형: {info_map.get(shift_type, shift_type)}\n"
                f"- 선택한 교대시간 없음\n"
                f"- 사전교대인원: {num_people or '-'}명\n"
                f"- 사전교대순번: {my_order or '-'}번"
            )
    send_notilab_push(msg)
    collection.insert_one({
            "sent_at": datetime.utcnow() + timedelta(hours=9),
            "shiftType": shift_type,
            "shiftOrder": shift_order,
            "shiftStart": shift_start,
            "shiftEnd": shift_end,
            "taskType": task_type,
            "numPeople": num_people,
            "myOrder": my_order,
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


    if shift_order != '2':
        if task_type == 'recycling':
            t = now.replace(hour=20, minute=0, second=0, microsecond=0)
            save_scheduled_message(t, "분리수거 시간입니다!")
        elif task_type == 'cleaning':
            t = now.replace(hour=20, minute=30, second=0, microsecond=0)
            save_scheduled_message(t, "화장실청소 시간입니다!")

    if shift_type == "afternoon":
        leave_alarm = now.replace(hour=22, minute=0, second=0, microsecond=0)
        save_scheduled_message(leave_alarm, "퇴근! 수고하셨습니다!")
    elif shift_type == "morning":
        leave_alarm = now.replace(hour=15, minute=0, second=0, microsecond=0)
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


    
