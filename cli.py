#!/usr/bin/env python3

import re
import os
import sys
import signal
import platform
if platform.system() != 'Windows':
	import readline
else:
	import ctypes
from struct import pack, unpack
from binascii import hexlify, unhexlify
import colorama

sys.path.append('..')
import debugger.gdb as gdb
import debugger.utils as utils
import debugger.DebugAdapter as DebugAdapter

(RED, GREEN, BROWN, NORMAL) = (utils.RED, utils.GREEN, utils.BROWN, utils.NORMAL)

# globals
arch = None
adapter = None
context_last = {}

#--------------------------------------------------------------------------
# COMMON DEBUGGER TASKS
#--------------------------------------------------------------------------

def context_display(pkt_T=None):
	global arch
	global adapter
	global context_last

	tid = adapter.thread_selected()
	print('thread 0x%X:' % tid)

	reg2val = {x:adapter.reg_read(x) for x in adapter.reg_list()}
	for (reg,val) in reg2val.items():
		bits2fmt = {8:'%02X', 16:'%04X', 32:'%08X', 64:'%016X', 128:'%032X'}
		fmt = bits2fmt.get(adapter.reg_bits(reg), '%X')
		print(('%s=0x'+fmt) % (reg, val))

	pc_name = {'aarch64':'pc', 'x86_64':'rip', 'x86':'eip'}[arch]
	pc = reg2val[pc_name]

	try:
		data = adapter.mem_read(pc, 16)
		if data:
			(asmstr, asmlen) = utils.disasm1(data, pc, arch)
			print('%s%016X%s: %s\t%s' % \
				(GREEN, pc, NORMAL, hexlify(data[0:asmlen]).decode('utf-8'), asmstr))
	except DebugAdapter.GeneralError as e:
		print('%s%016X%s: couldn\'t read mem' % \
			(GREEN, pc, NORMAL))

def thread_display():
	tid_selected = adapter.thread_selected()

	for tid in adapter.thread_list():
		adapter.thread_select(tid)
		reg_pc_val = adapter.reg_read(reg_pc)
		seltxt = ['','(selected)'][tid == tid_selected]
		print('Thread tid=0x%X %s=0x%X %s' % (tid, reg_pc, reg_pc_val, seltxt))

	adapter.thread_select(tid_selected)
	pass

def debug_status():
	return

#--------------------------------------------------------------------------
# MAIN
#--------------------------------------------------------------------------

def handler_sigint(signal, frame):
	global adapter
	print('sending "break into" signal')
	adapter.break_into()

def adjust_ctrl_c():
	kernel32 = ctypes.windll.kernel32
	# If the HandlerRoutine parameter is NULL,
	# a TRUE value causes the calling process to ignore CTRL+C input
	bRet = kernel32.SetConsoleCtrlHandler(0, True)
	#print("SetConsoleCtrlHandler(0, 1) returns %d\n", bRet)

	#handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
	#print("GetStdHandle(STD_INPUT_HANDLE) returns %d\n" % handle)
	#mode = c_uint()
	#pfunc = kernel32.GetConsoleMode
	#pfunc.restype = c_int
	#pfunc.argtypes = [POINTER(c_ulong)]
	#bRet = pfunc(byref(mode))
	#mode = mode.value
	#print("GetConsoleMode(%d) returns %08X\n" % (handle, mode))
	#mode |= ENABLE_PROCESSED_INPUT
	#bRet = kernel32.SetConsoleMode(handle, ENABLE_PROCESSED_INPUT)
	#print("SetConsoleMode(%d, %08X) returns %d\n" % (handle, mode, bRet))

if __name__ == '__main__':
	colorama.init()

	# set up ctrl+c for break-into
	signal.signal(signal.SIGINT, handler_sigint)
	if platform.system() == 'Windows':
		adjust_ctrl_c()

	adapter = None
	if not sys.argv[1:]:
		raise Exception('specify target on command line')
	arg1 = sys.argv[1]
	if ':' in arg1:
		(host, port) = arg1.split(':')
		adapter = gdb.DebugAdapterGdb()
		adapter.connect(host, int(port))
	else:
		if '~' in arg1:
			arg1 = os.expanduser(arg1)
		arg1 = os.path.abspath(arg1)
		if not os.path.exists(arg1):
			raise Exception('file not found: %s' % arg1)

		adapter = DebugAdapter.get_adapter_for_current_system()
		adapter.exec(arg1)

	arch = adapter.architecture()

	user_goal = 'debug'
	while user_goal == 'debug':
		try:
			text = input('FAKEDBG>')
			if not text:
				continue

			# testing stuff
			#elif text.startswith('packet '):
			#	reply = tx_rx(text[7:])
			elif text == 'test':
				adapter.test()
			elif text.startswith('raw '):
				print(adapter.raw(text[4:]))

			# thread list, thread switch
			elif text in ['~', 'threads']:
				thread_display()

			elif text[0:] and text[0]=='~' and text[-1]=='s':
				tid = int(text[1:-1], 16)
				print('switching to thread 0x%x' % tid)
				adapter.thread_select(tid)

			# breakpoint set/clear
			elif text.startswith('bp '):
				addr = int(text[3:], 16)
				adapter.breakpoint_set(addr)
				print('breakpoint set at 0x%X' % (addr))

			elif text.startswith('bc '):
				addr = int(text[3:], 16)
				adapter.breakpoint_clear(addr)
				print('breakpoint cleared at 0x%X' % addr)

			elif text == 'bl':
				print('breakpoint list:')
				for (i,addr) in enumerate(adapter.breakpoint_list()):
					print('%d: 0x%X' % (i, addr))

			# context, read regs, write regs
			elif text in ['r']:
				context_display()
			elif re.match(r'r \w+=.*$', text):
				(reg, val) = text[2:].split('=')
				adapter.reg_write(reg, int(val, 16))
			elif re.match(r'r \w+ .*$', text):
				(_, reg, val) = text.split(' ')
				adapter.reg_write(reg, int(val, 16))
			elif re.match(r'r \w+', text):
				(_, reg) = text.split(' ')
				val = adapter.reg_read(reg)
				print('%s=%016X' % (reg, val))

			# read/write mem, disasm mem
			elif text.startswith('db '):
				addr = int(text[3:], 16)
				data = adapter.mem_read(addr, 128)
				print(utils.hex_dump(data, addr))
			elif text.startswith('eb '):
				m = re.match(r'^eb (\w+) (.*)$', text)
				addr = int(m.group(1), 16)
				bytes_ = bytes(map(lambda x: int(x,16), m.group(2).split()))
				adapter.mem_write(addr, bytes_)
			elif text.startswith('u '):
				addr = int(text[2:],16)
				data = adapter.mem_read(addr, 32)
				print(utils.disasm(data, addr))
			elif text == 'lm':
				module2addr = adapter.mem_modules()
				for module in sorted(module2addr, key=lambda m: module2addr[m]):
					addr = module2addr[module]
					print('%016X: %s' % (addr, module))

			# break into, go, step, step into
			elif text in ['break', 'breakinto']:
				break_into()

			elif text in 'gpt':
				while 1:
					if text == 'g':
						(reason, data) = adapter.go()
					elif text == 't':
						(reason, data) = adapter.step_into()
					elif text == 'p':
						(reason, data) = adapter.step_over()

					if reason == DebugAdapter.STOP_REASON.STDOUT_MESSAGE:
						print('stdout: ', data)
					elif reason == DebugAdapter.STOP_REASON.PROCESS_EXITED:
						print('process exited, return code=%d' % data)
						break
					else:
						print('stopped, reason: %s' % reason.name)
						context_display()
						break

			# quit, detach, quit+detach
			elif text in ['q', 'quit', 'exit']:
				user_goal = 'quit'
				break
			elif text in ['qd', 'detach']:
				user_goal = 'detach'
				break

			# else
			else:
				print('unrecognized: %s' % text)

		except KeyboardInterrupt as e:
			print("ctrl+c detected! breaking in!\n")
			break_into()

	if user_goal == 'detach':
		adapter.detach()
	elif user_goal == 'quit':
		adapter.quit()

