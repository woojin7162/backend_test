from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

import logging

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def save_scheduled_message(run_time, content):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO scheduled_messages (content, run_time) VALUES (:content, :run_time)"),
            {"content": content, "run_time": run_time}
        )

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
    save_scheduled_message(now, msg)

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
    from sqlalchemy import MetaData, Table, Column, Integer, Text, TIMESTAMP
    metadata = MetaData()
    scheduled_messages = Table(
        "scheduled_messages",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("content", Text, nullable=False),
        Column("run_time", TIMESTAMP, nullable=False),
    )
    # 이미 위에서 engine을 만들었으니 재생성 필요 없음
    metadata.create_all(engine)

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)


