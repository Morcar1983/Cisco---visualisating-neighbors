# coding: utf-8
import netmiko as netm
import getpass, re
import ipaddress as cidr
import sys, os
import concurrent.futures
from pyvis.network import Network
sys.stderr = open(os.devnull,'w')

def user_input():
    """ Getting mgmt subnet, connection timeout, user name and password from a user"""
    mgmtnet='' # setting mgmt subnet as blank string
    while mgmtnet =='': # iterating through the loop while mgmt subnet is a blank string
        mgmtnet=input("Mgmt network in x.x.x.x/y (CIDR) notation: ") # getting user input on subnet
        if re.fullmatch(r'\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}/\d{2}',mgmtnet): # veryfing that input matches subnet pattern
            for i,j in enumerate(re.split('\.|/',mgmtnet)): # splitting the subnet into octets
                if int(j)>255 or (i == 4 and int(j) >32): # veryfing that mask isn't greater than 32 and that single octet isn't greater than 255
                    print('Invalid subnet') # printing error message if mask exceeds 32
                    mgmtnet='' # reseting the value so while loop can interate again
        else:
            print ("Doesn't look like a CIDR...") # if input doesn't match CIDR pattern print error message
            mgmtnet='' # reseting the value so while loop can interate again
    usrnm='' # setting usrnm as blank string
    while usrnm =='': # iterating through the loop while usrnm is a blank string
        usrnm=input ("Username: ") #requesting a username
        if usrnm=='': # if nothing is typed
            print("Username can't be blank") # print an error message
    usrpwd = getpass.getpass() # getting usr password
    return mgmtnet, usrnm, usrpwd # returning mgmt subnet, user name, user password
        
def device_conn(conn_info):
    """Connecting to devices and pulling neccessary information"""
    print(f'Connecting to device: {conn_info[0]}', end='\r') # indicating the current progress
    devstr=() #Tuple of IP/output of show cdp neighbor
    try:
       with netm.ConnectHandler(host=conn_info[0], username=conn_info[1], password=conn_info[2], device_type="cisco_ios", conn_timeout=5) as device: #connecting to device
           devstr += (conn_info[0], device.send_command("show cdp neighbors detail"),device.send_command("show version | i IOS"),
           device.send_command("show spanning-tree summary"), device.send_command("show ip dhcp snooping"),
           device.send_command("sh run | i hostname"), device.send_command("sh inv")) # getting output and puts in a tuple   
    except Exception as e:
        pass
    return devstr # return tuple of IP + neighbor string + software string + spanning tree summary + ip dhcp snooping + hostname

def concurent_conn_wrapper(data):
    devicelist = [[str(ip),data[1],data[2]] for ip in cidr.IPv4Network(data[0])] # filling in IP addresses into the list
    if len(devicelist) != 1: # if list isn't single ip = /32
        devicelist = devicelist[1:len(devicelist)-1] #then slice out subnet and broadcast addresses
    with concurrent.futures.ProcessPoolExecutor(20) as executor: # concurent connections procedure - spawning 20 concurent processes
        results = [item for item in executor.map(device_conn, devicelist)]
    results_cleaned = list (filter (lambda x: x != (), results)) # removing empty tuples
    return results_cleaned

def data_extract(*neighbor_string):
    """Checking the neighbor string from a device and finding out the neighbors"""
    neighbor_list_dict={} # preparing a dict which will contain host list on a network together with the given properties
    for host, neighbor, soft, sptree, dhcpsno, hostname, serial in (neighbor_string): # iterating through the hosts
        dhcpsno_new = ((re.findall(r'Switch DHCP snooping is (\S*)',dhcpsno))[0] if (re.findall(r'Switch DHCP snooping is (\S*)',dhcpsno)) else 'disabled') # extracting DHCP snooping ingo
        sptree_new = ((re.findall(r'Switch is in (\S*) mode',sptree))[0] if (re.findall(r'Switch is in (\S*) mode',sptree)) else 'disabled') # extracting Spanning tree info
        hostname_new = ((re.findall(r'hostname (\S*)',hostname))[0] if (re.findall(r'hostname (\S*)',hostname)) else 'N/A') # extracting hostname
        serial_new = ((re.findall(r'SN: (\S*)',serial))[0] if (re.findall(r'SN: (\S*)',serial)) else 'N/A') # extracting serial number
        model_new = ((re.findall(r'PID: (\S*)',serial))[0] if (re.findall(r'PID: (\S*)',serial)) else 'N/A') # extracting model number
        soft_new = ((re.findall(r'Version (\S*, RELEASE SOFTWARE \S*)',soft))[0] if (re.findall(r'Version (\S*, RELEASE SOFTWARE \S*)',soft)) else 'N/A') # extracting software version 
        neigh_name = (re.findall(r'Device ID: (\S*)', neighbor)) # extracting neighbor names
        for count, oc in enumerate(neigh_name): # iterating thorugh neigbor names
            if '.owenscorn' in oc: # removing domain from hostname
                word = oc.split('.')
                neigh_name[count]=word[0]
        #neigh_IP = (re.findall(r'Entry address\(es\): \n  IP address: (\S*)', neighbor)) # extracting neigbor IPs
        neigh_IP = (re.findall(r'Entry address\(es\): \n(.+)', neighbor)) # extracting neigbor IPs
        for count, ips in enumerate(neigh_IP): # checking if neigbor has got an IP
            neigh_IP[count] = (re.findall(r'IP address: (\S*)', ips)[0] if (re.findall(r'IP address: (\S*)',ips)) else neigh_name[count]) # assigning device name instead of IP if device has got no IP
        neigh_local_port = (re.findall(r'Interface: (\S*\b)', neighbor)) # extracting local neighbor ports
        neigh_remote_port = (re.findall(r'Port ID \(outgoing port\): (\S*)', neighbor)) # extracting remote neighbor ports
        neighbor_list_dict.update ({host: [{'hostname':hostname_new},{'serial':serial_new},{'software version':soft_new},{'DHCP snooping':dhcpsno_new},{'SPT type':sptree_new},
        {'neighbors':list(zip(neigh_name,neigh_IP,neigh_local_port, neigh_remote_port))},{'model':model_new}]}) # creating a dictionary entry, zipping together all the extracted info
    return neighbor_list_dict #return dict of IP + neighbot list
    
def graph_creator(**data):
    """building an html graph based on the data"""
    field_meas=('2000px' if len(data)>64 else '1000px') # setting the size of the field
    graph = Network(field_meas, field_meas, directed = True) # creating network object to host the graph
    graph.set_edge_smooth('dynamic') # allowing multi edges connections between two nodes
    for host in data.keys(): # iterating through hosts in the network
        color=''; size = 15; title = ''; shape = 'box' # clearing the variables used in the loop
        color = ('red' if (data[host][3]['DHCP snooping'] !='enabled' or data[host][4]['SPT type'] !='rapid-pvst') else 'green' ) # setting the color: green if RPVST and DHCP snooping enabled, red otherwise
        if 'MDFCS' in data[host][0]['hostname']:
            size = 15
            shape = 'circle'
        title = host + '<br>' + 'hostname:'+data[host][0]['hostname'] + '<br>' + 'model:'+data[host][6]['model'] + '<br>' +'serial:'+data[host][1]['serial'] + '<br>' + 'software:'+data[host][2]['software version'] + '<br>' + 'DHCP snooping:'+data[host][3]['DHCP snooping']+ '<br>' + 'SPT type:'+data[host][4]['SPT type'] # setting the tooltip
        graph.add_node(host, label=data[host][0]['hostname'], title=title, color=color, size = size, shape=shape) # adding a node to the list
    for host in data.keys(): # iterating through host in the network again - this time for setting edges
        for edge_conn in data[host][5]['neighbors']: # iterating through the neighbors of particular host
            if edge_conn[1] not in graph.nodes: # if neighbor isnt' in the node list then create it
                graph.add_node(edge_conn[1], label=edge_conn[0], title=edge_conn[1]+'<br>'+'hostname:'+edge_conn[0],color = 'blue', size = 10) # creating the node
            if graph.get_nodes().index(host) < graph.get_nodes().index(edge_conn[1]): # if edge is to be terminated to the node after this node in the node list - then creating edge
                graph.add_edge(host,edge_conn[1],title=data[host][0]['hostname']+'['+edge_conn[2]+']'+'--'+edge_conn[0]+'['+edge_conn[3]+']') # creating edge
    graph.show('nx.html') # showing the graph in browser
    
def runner():
    raw_device_data=concurent_conn_wrapper(user_input())
    device_data_sorted = data_extract(*raw_device_data) # extracting neccesry info from switch output
    graph_builder = graph_creator(**device_data_sorted) # building and showing a graph in the browser
    
if __name__== "__main__":
    runner()
    
