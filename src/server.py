#!/usr/bin/python3

import socket
import ipaddress
import signal
import sys
import re
PACKET_SIZE = 1024

# exit gracefully....
def sigint_handler(signal, frame):
    sys.exit(0)
signal.signal(signal.SIGINT, sigint_handler)

def translate_name(name, req_type):
    # let's construct the response...
    try:
        if req_type == "A":
            try: # cannot ask for A given an address
                socket.inet_aton(name)
                return None, True # bad request
            except OSError:
                answer = socket.gethostbyname(name)

        elif req_type == "PTR":
            try: # cannot ask for PTR given a domain name
                socket.inet_aton(name)
            except OSError:
                return None, True # Bad request
            answer, __, __  = socket.gethostbyaddr(name)

        else:
            return None, True # Bad request
    except socket.gaierror:
            return None, False # Not found

    # avoid asking for A given an address and for PTR given a PTR..
    if name == answer:
        return None, True # Bad request
    return answer, False

def handle_get(data):
    response = "HTTP/1.1 200 OK\r\n\r\n"
    request = data.split('\n')[0]

    # check the request format...
    matcher_get = re.compile(r'GET /resolve\?name=(((?:[0-9]{1,3}\.){3}[0-9]{1,3})|((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9]))&type=(A|(PTR)) HTTP/1\.1')
    if re.fullmatch(matcher_get, request) == None:
        return "HTTP/1.1 400 Bad Request\r\n\r\n"

    # extract the name and type
    request = request.split(' ')[1].split('?')[1]
    name = request.split('&')[0][5:]
    req_type = request.split('&')[1][5:]

    # get the translation..
    answer, bad_request = translate_name(name, req_type)
    if answer is None:
        if bad_request == True:
            return "HTTP/1.1 400 Bad Request\r\n\r\n"
        else:
            return "HTTP/1.1 404 Not Found\r\n\r\n"

    response += name + ':' + req_type + '=' + answer + '\r\n'
    return response


def handle_post(data):
    response_header = "HTTP/1.1 200 OK\r\n\r\n"
    response = ""

    request = data.split('\n')[0]
    if request != "POST /dns-query HTTP/1.1":
        return "HTTP/1.1 400 Bad Request\r\n\r\n"

    # slice off the header and split by \n
    data = data[data.find('\n\n') + 2:].split('\n')
    if data != []:
        if data[-1] == '':
            data.pop()

    bad_request = False
    matcher_post = re.compile(r'^(((?:[0-9]{1,3}\.){3}[0-9]{1,3})|((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9]))[ ]*:[ ]*(A|(PTR))[ ]*$') # format of the query
    for item in data:
        # check the query format...
        if re.fullmatch(matcher_post, item) == None:
            bad_request = True
            continue

        query = item.split(':')
        name = query[0].strip()
        req_type = query[1].strip()
        answer, __ = translate_name(name, req_type)
        if answer is None:
            continue
        response += name + ':' + req_type + '=' + answer + '\r\n'

    # There were either no queries at all or there was no query that was
    # of the  correct format 
    if response == "":
        if bad_request == True:
            return "HTTP/1.1 400 Bad Request\r\n\r\n"
        else:
            return "HTTP/1.1 404 Not Found\r\n\r\n"

    return response_header + response

# _____________ MAIN _____________
if len(sys.argv) != 2:
    sys.stderr.write('Please specify a port number.\n')
    sys.exit(500)

# get port number from program argument
arg = sys.argv[1]
if not arg.isnumeric():
    sys.exit(500)

port = int(arg)
if not 0 <= port <= 65535: # check port value
    sys.exit(500)

# create server socket and set flags to avoid errors when relaunching the server
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    s.bind(('localhost', port))
except PermissionError:
    sys.exit(500)

s.listen()

while True:
    client_sock, address = s.accept()

    with client_sock:
        data = client_sock.recv(PACKET_SIZE).decode()
        if not data:
            break

        data = data.replace('\r\n', '\n') # unify newlines...
        req_method = data.split(' ')[0]
        
        if req_method == "GET":
            response = handle_get(data)

        elif req_method == "POST":

            # In case the length of data in the request is bigger than the default
            # packet size, recieve the rest
            data_len = data.split('\n\n')[0].split('\n')[4].split(' ')[1]
            if data_len.isnumeric():
                data_len = int(data_len)
                if data_len > PACKET_SIZE:
                    iterations = data_len // PACKET_SIZE
                    while iterations > 0:
                        data_chunk = client_sock.recv(PACKET_SIZE)
                        data += data_chunk.decode()
                        iterations -= 1

            data = data.replace('\r\n', '\n')
            response = handle_post(data)

        else: # unknown method...
            response = "HTTP/1.1 405 Method Not Allowed\r\n\r\n"

        client_sock.sendall(response.encode())
        try: client_sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        client_sock.close()

s.shutdown(socket.SHUT_RDWR)
s.close()
