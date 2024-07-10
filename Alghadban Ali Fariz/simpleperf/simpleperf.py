import argparse
import socket
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# Function to check if the input value is positive
def check_positive(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("%s is an invalid positive value" % value)
    return ivalue

# Function to convert the input string to bytes
def num_bytes(value):
    if value[-2:] == "KB":
        return int(value[:-2]) * 1000
    elif value[-2:] == "MB":
        return int(value[:-2]) * 1000000
    elif value[-1:] == "B":
        return int(value[:-1])
    else:
        raise argparse.ArgumentTypeError("Invalid format for --num. Use B, KB, or MB.")
    
# Function to run the server
def run_server(args):
    server(args.bind, args.port, args.format)

# Function to run the client
def run_client(args):
    # Change the condition to check if both args.num and args.time are None
    if args.num is None and args.time is None:
        args.time = 25  # Default time
    elif args.num is not None and args.time is not None:
        print('Error: you cannot use both --num and --time at the same time.')
        return

    # Use ThreadPoolExecutor to manage multiple client connections
    with ThreadPoolExecutor(max_workers=args.connections) as executor:
        # Pass the args.time to the client function as the duration
        futures = [executor.submit(client, args.serverip, args.port, args.num, args.time, args.format, args.interval, i + 1) for i in range(args.connections)]

        for future in futures:
            future.result()

# Main function to handle command line arguments and run server/client
def main():
    parser = argparse.ArgumentParser(description='Simpleperf client and server mode.')
    parser.add_argument('-s', '--server', action='store_true', help='Enable server mode')
    parser.add_argument('-b', '--bind', type=str, default='', help='IP address to bind the server')
    parser.add_argument('-p', '--port', type=int, default=8088, help='Port number for the server to listen on')
    parser.add_argument('-f', '--format', type=str, default='MB', help='Summary format (B, KB, MB)')
    parser.add_argument('-n', '--num', type=num_bytes, default=None, help='Number of bytes to transfer (B, KB, MB)')
    parser.add_argument('-c', '--client', action='store_true', help='Enable client mode')
    parser.add_argument('-I', '--serverip', type=str, default='127.0.0.1', help='IP address of the server')
    parser.add_argument('-t', '--time', type=check_positive, default=None, help='Duration for sending data in seconds (time > 0)')
    parser.add_argument('-i', '--interval', type=check_positive, default=None, help='Print statistics per z seconds (z > 0)')
    parser.add_argument('-P', '--connections', type=check_positive, default=1, help='Number of parallel connections')

    args = parser.parse_args()

    if not args.server and not args.client:
        print('Error: you must run either in server or client mode.')
        return

    if args.server:
        run_server(args)
    elif args.client:
        run_client(args)



# Server function to handle incoming client connections
def handle_client(conn, addr, format):
        server_ip, server_port = conn.getsockname() # Get the server IP and port
        with conn:
            # Print connection information
            print(f'A simpleperf client with {addr[0]}:{addr[1]} is connected with {server_ip}:{server_port}')

            start_time = time.time() # Record the start time of the connection
            total_received = 0 # Initialize the total data received

            try:
              while True:
                data = conn.recv(1000) # Receive data from the client
                if data == b'BYE':  # Check if the client sent a 'BYE' message
                    conn.sendall(b'ACK: BYE')  # Send 'ACK: BYE' back to the client
                    break
                total_received += len(data) # Add the length of received data to the total
            except socket.error:
                pass # Handle socket errors

            end_time = time.time()  # Record the end time of the connection
            elapsed_time = end_time - start_time   # Calculate the elapsed time
            bandwidth = total_received / elapsed_time  # Calculate the bandwidth

            # Convert the total_received and bandwidth to the desired format (KB or MB)
            if format == 'KB':
                total_received /= 1000
                bandwidth /= 1000
            elif format == 'MB':
                total_received /= 1000000
                bandwidth /= 1000000
            
            # Print the connection statistics
            print(f'ID\t\tInterval\t\tReceived\tRate')
            print(f'{addr}\t0.0 - {elapsed_time:.1f}\t{total_received:.1f} {format}\t{bandwidth:.1f} Mbps')

# Server function to listen for incoming connections
def server(bind_ip, port, format):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((bind_ip, port)) # Bind the server to the specified IP and port
        s.listen()   # Start listening for connections
        print(f'A simpleperf server is listening on port {port}')

        while True:
            conn, addr = s.accept()  # Accept an incoming connection
            # Create a new thread to handle the client connection
            client_thread = threading.Thread(target=handle_client, args=(conn, addr, format))
            client_thread.start()

# Function to print connection interval statistics during data transfer
def print_connection_interval_stats(connection_id, client_ip, client_port, start_time, prev_total_sent, format, interval, total_sent):
    current_time = time.time()
    elapsed_time = current_time - start_time
    interval_elapsed_time = elapsed_time - interval

    interval_transfer = (total_sent - prev_total_sent)
    interval_bandwidth = (interval_transfer / (1024 * 1024)) / interval  # MBps

    if format == 'KB':
        interval_transfer /= 1024
        interval_bandwidth *= 1024
    elif format == 'MB':
        interval_transfer /= (1024 * 1024)

    print(f'({connection_id}) {client_ip}:{client_port}\t{interval_elapsed_time:.1f} - {elapsed_time:.1f}s\t{interval_transfer:.1f} {format}\t{interval_bandwidth:.1f} MBps')


print_connection_interval_stats.prev_total_sent = 0

# Client function to connect to the server, send data, and display interval statistics
def client(server_ip, port, num_bytes, duration, format, interval, connection_id):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        print(f'A simpleperf client ({connection_id}) connecting to server {server_ip}, port {port}')
        s.connect((server_ip, port))
        client_ip, client_port = s.getsockname()
        print(f'Client ({connection_id}) connected with {server_ip} port {port}')

        start_time = time.time()
        last_print_time = start_time if interval is not None else None
        total_sent = 0
        prev_total_sent = 0

        # Send initial message to server indicating the start of transfer
        start_msg = f'START {start_time}\n'
        s.sendall(start_msg.encode())

        # Helper functions
        def should_send_more_data():
            return num_bytes is None or total_sent < num_bytes
        
        # Function to send data to the server
        def send_data():
            nonlocal total_sent, prev_total_sent
            to_send = min(1000, num_bytes - total_sent) if num_bytes is not None else 1000
            s.sendall(b'0' * to_send)
            total_sent += to_send

        # Function to check and print interval statistics during data transfer
        def check_and_print_interval_stats():
            nonlocal prev_total_sent, last_print_time
            if interval is not None and time.time() - last_print_time >= interval:
                print_connection_interval_stats(connection_id, client_ip, client_port, start_time, prev_total_sent, format, interval, total_sent)
                last_print_time = time.time()
                prev_total_sent = total_sent
                
        # Calculate end_time if duration is specified        
        if duration is not None:
               end_time = start_time + duration

        # Main loop for sending data and checking interval statistics
        while should_send_more_data():

            send_data()
            check_and_print_interval_stats()

            if duration is not None and time.time() >= end_time:
                break
            

        
        # Ending the connection and printing final statistics
        time.sleep(1)
        s.sendall(b'BYE')
        data = s.recv(1000)
        if data == b'ACK: BYE':
            elapsed_time = time.time() - start_time
            bandwidth = total_sent / elapsed_time

            if format == 'KB':
                total_sent /= 1000
                bandwidth /= 1000
            elif format == 'MB':
                total_sent /= 1000000
                bandwidth /= 1000000
            print('----------------------------------------------------------')
            print(f'ID\t\tInterval\tTransfer\tBandwidth')
            print(f'{client_ip}:{client_port}\t0.0 - {elapsed_time:.1f}s\t{total_sent:.1f} {format}\t{bandwidth:.1f} MBps')
if __name__ == '__main__':
    main()
