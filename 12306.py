#-*- coding:utf-8 -*-
import sys, time,json
import requests, socket, logging
import config, mail, seat_code, query_db


logging.basicConfig(level=config.log_level,
                format=config.log_format,
                datefmt=config.log_datefmt,
                filename=config.log_filename,
                filemode=config.log_filemode)

db = query_db.QueryDB()
db.connect()

def has_ticket(info, valid_trips, valid_seats):
	for number in range(len(info)):
		trip = info[number]['queryLeftNewDTO']
		trip_number = trip['station_train_code']
		# 如果不是想要的车次，那就跳过
		if len(valid_trips) != 0 and (trip_number not in valid_trips):
			continue

		for seat in seat_code.code_map.values():
			# 如果不是想要的座位，就跳过
			if len(valid_seats) != 0 and (seat not in valid_seats):
				continue
			seat_num = trip[seat];
			if seat_num == '有' or (seat_num.isdigit() and int(seat_num) > 0):
				return trip_number

	return False

# 修改数据库数据状态
def modify_status(id_num, status):
	db.execute("UPDATE trainquery.querylist SET `status`=%s WHERE `id` = %s", [status, id_num])

try:
	while True:
		# 12306的运行时间是7:00~23:00，此时间外不进行查票，且脚本运行间隔为闲时间隔
		hour = time.localtime().tm_hour
		if hour >= 23 or hour < 6:
			time.sleep(config.timegap_free) # 闲时间隔
		else:
			time.sleep(config.timegap_busy) # 忙时间隔

		if hour >= 23 or hour < 7: # 交易时间外不进行查票
			continue
	
		# 查数据库
		cursor = db.query("SELECT * FROM trainquery.querylist WHERE `status`='init'")
		querylist = cursor.fetchall()
		if len(querylist) == 0:
			logging.info('nothing to query, hahaha...')
			break

		for query_request in querylist:
			# 参数获取
			id_num = query_request[0]
			from_station = query_request[1]
			to_station = query_request[2]
			query_date = query_request[3]
			valid_trips_in_db = query_request[4]
			valid_seats_in_db = query_request[5]
			query_request_json = '[{},{},{},{},{},{}]'.format(id_num, from_station, to_station, query_date, valid_trips_in_db, valid_seats_in_db)
			valid_trips = []
			valid_seats = []
			if valid_trips_in_db != None and valid_trips_in_db != '':
				valid_trips = valid_trips_in_db.split(',')
			if valid_seats_in_db != None and valid_seats_in_db != '':
				valid_seats = valid_seats_in_db.split(',')
			url = 'https://kyfw.12306.cn/otn/leftTicket/queryZ?leftTicketDTO.train_date={}&leftTicketDTO.from_station={}&leftTicketDTO.to_station={}&purpose_codes=ADULT'.format(query_date,from_station,to_station)

			query_begin_time = time.time()

			# 查询12306
			try:
				result = requests.get(url, verify=False, timeout=600)   # 不用验证证书
			except socket.timeout:
				mail.email('服务停止，12306返回超时, input=' + query_request_json)
				logging.error(query_request_json + ' timeout')
			except requests.exceptions.ReadTimeout:
				mail.email('服务停止，12306返回超时, input=' + query_request_json)
				logging.error(query_request_json + ' timeout')
			except ConnectionError as err:
				mail.email('服务停止，连接出现问题, error: ' + str(err))
				logging.error(query_request_json + ' connection error, error=' + str(err))

			# 转换json格式
			try:
				info = result.json()
			except ValueError:
				logging.error(query_request_json + ' ValueError: No JSON object could be decoded, value=' + result.text)
				continue;

			# 日志
			query_end_time = time.time()
			logging.info(query_request_json + ' , take time: ' + str(query_end_time - query_begin_time) + 's')

			if info['status'] and 'data' in info.keys():
				ticket_result = has_ticket(info['data'], valid_trips, valid_seats)
				if ticket_result:
					logging.info('Get it!')
					logging.info(ticket_result)
					mail.email(query_request_json + ' 有票啦，车次号: ' + str(ticket_result))
					modify_status(id_num, 'done')

			else:
				logging.error('{} Error!!, info={}'.format(query_request_json, info))
				mail.email(query_request_json + ' 查询失败， info=' + str(info))
				modify_status(id_num, 'bad')
finally:
	db.close()