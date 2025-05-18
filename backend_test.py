from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

app = Flask(__name__)
CORS(app)
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def send_discord_message(content):
    if not DISCORD_WEBHOOK_URL:
        print("웹훅 URL이 설정되지 않았습니다.")
        return None
    payload = {
        "content": content,
        "username": "교대근무 알리미"
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")
        elif resp.status_code == 204:
            print("메시지 ID를 받을 수 없습니다 (204 No Content)")
            return None
    except Exception as e:
        print("웹훅 전송 오류:", e)
    return None



def delete_discord_message(message_id):
    if not DISCORD_WEBHOOK_URL or not message_id:
        return
    delete_url = f"{DISCORD_WEBHOOK_URL}/messages/{message_id}"
    try:
        resp = requests.delete(delete_url, timeout=5)
        if resp.status_code == 204:
            print("메시지 삭제 성공")
        else:
            print("메시지 삭제 실패:", resp.status_code, resp.text)
    except Exception as e:
        print("메시지 삭제 오류:", e)





def schedule_alarm(run_time, content):
    if run_time > datetime.now():
        scheduler.add_job(
            send_discord_message,
            trigger=DateTrigger(run_date=run_time),
            args=[content],
            id=f"{run_time.strftime('%Y%m%d%H%M')}_{hash(content)}",
            replace_existing=True
        )
        print(f"알림 예약: {run_time} - {content}")

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



    now = datetime.now() + timedelta(hours=9)
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
        
    send_discord_message(msg)
    msg_id = send_discord_message(msg)
    delete_time = None
    if shift_type == "morning":
        delete_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    elif shift_type == "afternoon":
        delete_time = now.replace(hour=0, minute=55, second=0, microsecond=0)

# 삭제 예약 (msg_id가 있고, 예약 시간이 미래일 때만)
    if msg_id and delete_time and delete_time > datetime.now():
        scheduler.add_job(
            delete_discord_message,
            trigger=DateTrigger(run_date=delete_time),
            args=[msg_id],
            id=f"delete_{msg_id}",
            replace_existing=True
    )
    print(f"메시지 삭제 예약: {delete_time} - 메시지ID: {msg_id}")





    if shift_type == "morning":
    # morningTimes는 ["10", "11", ...] 형태의 리스트
        morning_times = data.get("morningTimes", [])
        for t in morning_times:
            try:
                hour = int(t)
            except ValueError:
                continue
        # 시작 알림: (선택한 시각 - 1)시 54분
            start_alarm = now.replace(hour=hour-1, minute=54, second=0, microsecond=0)
        # 종료 알림: (선택한 시각) 54분
            end_alarm = now.replace(hour=hour, minute=54, second=0, microsecond=0)
        # 오전 1,2시는 13,14로 들어오므로 12시간제 표기 보정
            schedule_alarm(start_alarm, "포스 시작 교대 시간입니다!")
            schedule_alarm(end_alarm, "포스 종료 교대 시간입니다! 주차장을 확인해주세요!")



    if shift_type == 'afternoon':
        # 4~10시 1-2-3 반복 교대 (포스 교대 시작/종료)
        order_times = {
            '1': [(16, 17), (19, 20)],
            '2': [(17, 18), (20, 21)],
            '3': [(18, 19), (21, 22)]
        }
        for start_hour, end_hour in order_times.get(shift_order, []):
            # 시작 알림 (시작 1분 전)
            start_alarm = now.replace(hour=start_hour-1, minute=54, second=0, microsecond=0)
            end_alarm = now.replace(hour=end_hour-1, minute=54, second=0, microsecond=0)
            schedule_alarm(start_alarm, f"포스 시작 교대 시간입니다! (순번 {shift_order})번")
            schedule_alarm(end_alarm, f"포스 종료 교대 시간입니다! 주차장을 확인해주세요! (순번 {shift_order})")

        # 2~4시 or 3~4시 구간별 1~3번 교대
        if shift_time_range == '2-4':
            # 1번: 13:55~14:35, 2번: 14:35~15:15, 3번: 15:15~15:55
            times = [
                (1, 13, 55, 14, 35),
                (2, 14, 35, 15, 15),
                (3, 15, 15, 15, 55)
            ]
        else:
            # 1번: 14:55~15:15, 2번: 15:15~15:35, 3번: 15:35~15:55
            times = [
                (1, 14, 55, 15, 15),
                (2, 15, 15, 15, 35),
                (3, 15, 35, 15, 55)
            ]
        for num, sh, sm, eh, em in times:
            if str(num) == shift_order:
                start = now.replace(hour=sh, minute=sm-1, second=0, microsecond=0)  # 1분 전
                end = now.replace(hour=eh, minute=em-1, second=0, microsecond=0)
                schedule_alarm(start, f"포스 시작 교대 시간입니다! ({sh}:{sm:02d}, 순번 {num})")
                schedule_alarm(end, f"포스 종료 교대 시간입니다! ({eh}:{em:02d}, 순번 {num})")

        # 분리수거/화장실청소 알림
    if shift_order != '2':
        if task_type == 'recycling':
            t = now.replace(hour=20, minute=0, second=0, microsecond=0)
            schedule_alarm(t, "분리수거 시간입니다!")
        elif task_type == 'cleaning':
            t = now.replace(hour=20, minute=30, second=0, microsecond=0)
            schedule_alarm(t, "화장실청소 시간입니다!")


 # 22:00 퇴근 알림
    leave_alarm = now.replace(hour=22, minute=0, second=0, microsecond=0)
    schedule_alarm(leave_alarm, "퇴근! 수고하셨습니다!")

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
