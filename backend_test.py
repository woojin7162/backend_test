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

DISCORD_WEBHOOK_URL = os.environ.get("https://discord.com/api/webhooks/1367799493516329030/gnKtt12do5kMGgv4JhsWAkX05-OzhV2FteNEgWTj7E5SMy-uf1bRBaZnrg5dC0-ii7jk")

def send_discord_message(content):
    if not DISCORD_WEBHOOK_URL:
        print("웹훅 URL이 설정되지 않았습니다.")
        return
    payload = {"content": content}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print("웹훅 전송 오류:", e)

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

    now = datetime.now()
    shift_type = data['shiftType']
    shift_order = data['shiftOrder']
    shift_time_range = data['shiftTimeRange']
    task_type = data['taskType']

    send_discord_message("근무 시간 접수 완료")
    
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
            schedule_alarm(start_alarm, f"포스 교대 시작! ({start_hour}시, 순번 {shift_order})")
            schedule_alarm(end_alarm, f"포스 교대 종료! ({end_hour}시, 순번 {shift_order})")

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
                schedule_alarm(start, f"포스 교대 시작! ({sh}:{sm:02d}, 순번 {num})")
                schedule_alarm(end, f"포스 교대 종료! ({eh}:{em:02d}, 순번 {num})")

        # 분리수거/화장실청소 알림
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
