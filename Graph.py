import netmiko as netm
import getpass, re
import ipaddress as cidr
import sys, os
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
    con_out=input ("Enter connection timeout between 1 (in case devices in LAN) and 9(in case devices in slow WAN) or leave it blank for default of 5 sec ")
    con_out = (con_out if re.fullmatch(r'\d{1}', con_out) else 5) # checking the input and assgining its value if it is within 1..9 range, otherwise assigning 5 to timeout
    usrnm='' # setting usrnm as blank string
    while usrnm =='': # iterating through the loop while usrnm is a blank string
        usrnm=input ("Username: ") #requesting a username
        if usrnm=='': # if nothing is typed
            print("Username can't be blank") # print an error message
    usrpwd = getpass.getpass() # getting usr password
    return mgmtnet, usrnm, usrpwd, con_out # returning mgmt subnet, user name, user password and connection timeout back to caller
        
def device_conn(mgmtnet,usrnm,usrpwd,con_out):
    """Connecting to devices and pulling neccessary information"""
    print('Connecting to devices...')
    devstr=() #Tuple of IP/output of show cdp neighbor
    devicelist = [str(ip) for ip in cidr.IPv4Network(mgmtnet)] # filling in IP addresses into the list
    if len(devicelist) != 1: # if list isn't single ip = /32
        devicelist = devicelist[1:len(devicelist)-1] #then slice out subnet and broadcast addresses
    for num, item in enumerate(devicelist): #iterating through devices
        print(f'{num/len(devicelist):.0%}', end='\r') #printing the progress figure
        try:
           with netm.ConnectHandler(host=item, username=usrnm, password=usrpwd, device_type="cisco_ios", conn_timeout=5) as device: #connecting to device
               devstr += ((item, device.send_command("show cdp neighbors detail"),device.send_command("show version | i IOS"),
               device.send_command("show spanning-tree summary"), device.send_command("show ip dhcp snooping"),
               device.send_command("sh run | i hostname"), device.send_command("sh inv")),) # getting output and puts in a tuple   
        except Exception as e:
            pass
    print('Done!')
    return devstr # return tuple of IP + neighbor string + software string + spanning tree summary + ip dhcp snooping + hostname

def data_extract(*neighbor_string):
    """Checking the neighbor string from a device and finding out the neighbors"""
    neighbor_list_dict={} # preparing a dict which will contain host list on a network together with the given properties
    for host, neighbor, soft, sptree, dhcpsno, hostname, serial in (neighbor_string): # iterating through the hosts
        dhcpsno_new = ((re.findall(r'Switch DHCP snooping is (\S*)',dhcpsno))[0] if (re.findall(r'Switch DHCP snooping is (\S*)',dhcpsno)) else 'disabled') # extracting DHCP snooping ingo
        sptree_new = ((re.findall(r'Switch is in (\S*) mode',sptree))[0] if (re.findall(r'Switch is in (\S*) mode',sptree)) else 'disabled') # extracting Spanning tree info
        hostname_new = ((re.findall(r'hostname (\S*)',hostname))[0] if (re.findall(r'hostname (\S*)',hostname)) else 'N/A') # extracting hostname
        serial_new = ((re.findall(r'SN: (\S*)',serial))[0] if (re.findall(r'SN: (\S*)',serial)) else 'N/A') # extracting serial number
        soft_new = ((re.findall(r'Version (\S*, RELEASE SOFTWARE \S*)',soft))[0] if (re.findall(r'Version (\S*, RELEASE SOFTWARE \S*)',soft)) else 'N/A') # extracting software version 
        neigh_name = (re.findall(r'Device ID: (\S*)', neighbor)) # extracting neighbor names
        neigh_IP = (re.findall(r'Entry address\(es\): \n  IP address: (\S*)', neighbor)) # extracting neigbor IPs
        neigh_local_port = (re.findall(r'Interface: (\S*\b)', neighbor)) # extracting local neighbor ports
        neigh_remote_port = (re.findall(r'Port ID \(outgoing port\): (\S*)', neighbor)) # extracting remote neighbor ports
        neighbor_list_dict.update ({host: [{'hostname':hostname_new},{'serial':serial_new},{'software version':soft_new},{'DHCP snooping':dhcpsno_new},{'SPT type':sptree_new},
        {'neighbors':list(zip(neigh_name,neigh_IP,neigh_local_port, neigh_remote_port))}]}) # creating a dictionary entry, zipping together all the extracted info
    return neighbor_list_dict #return dict of IP + neighbot list
    
def graph_creator(**data):
    """building an html graph based on the data"""
    graph = Network('1000px','1000px',directed = True) # creating network object to host the graph
    graph.set_edge_smooth('dynamic') # allowing multi edges connections between two nodes
    for host in data.keys(): # iterating through hosts in the network
        color=''; size = ''; title = '' # clearing the variables used in the loop
        color = ('red' if (data[host][3]['DHCP snooping'] !='enabled' or data[host][4]['SPT type'] !='rapid-pvst') else 'green' ) # setting the color: green if RPVST and DHCP snooping enabled, red otherwise
        size = (30 if 'Switch1' in data[host][0]['hostname'] else 15) # setting the size: 30 for MDF switch, 15 otherwise
        title = host + '<br>' + 'hostname:'+data[host][0]['hostname'] + '<br>' + 'serial:'+data[host][1]['serial'] + '<br>' + 'software:'+data[host][2]['software version'] + '<br>' + 'DHCP snooping:'+data[host][3]['DHCP snooping']+ '<br>' + 'SPT type:'+data[host][4]['SPT type'] # setting the tooltip
        graph.add_node(host, label=data[host][0]['hostname'], title=title, color=color, size = size, shape='box') # adding a node to the list
    for host in data.keys(): # iterating through host in the network again - this time for setting edges
        for edge_conn in data[host][5]['neighbors']: # iterating through the neighbors of particular host
            if edge_conn[1] not in graph.nodes: # if neighbor isnt' in the node list then create it
                graph.add_node(edge_conn[1], label=edge_conn[0], title=edge_conn[1]+'<br>'+'hostname:'+edge_conn[0],color = 'blue', size = 10) # creating the node
            if graph.get_nodes().index(host) < graph.get_nodes().index(edge_conn[1]): # if edge is to be terminated to the node after this node in the node list - then creating edge
                graph.add_edge(host,edge_conn[1],title=data[host][0]['hostname']+'['+edge_conn[2]+']'+'--'+edge_conn[0]+'['+edge_conn[3]+']') # creating edge
    graph.show('nx.html') # showing the graph in browser
    
def software_ver(*software_string):
    """Checking the software string from a device and finding out the version"""
    software_ver_dict={}
    for host, neighbor, soft in (software_string):
        if soft !='':
            soft_ver = (re.findall(r'Version (\S*, RELEASE SOFTWARE \S*)',soft))[0]
            software_ver_dict.update({host:soft_ver})
    return software_ver_dict #return IP + soft ver
 
def printing_output(neighbor_list, software_list):
    """Printing the output as a table"""
    #print(neighbor_list,software_list)
    print('IP\t\t\t\t\t\t\tNeighbors \t\t\t\t\tSoftware')
    delim='--'
    for ip,host in neighbor_list.items():
        for count, keyn in enumerate(host):
            if count==0:
                print(' ')
                print (f'{ip:16}{keyn:>40}@{host[keyn]:31}{software_list[ip]}')
            else:
                print (f'{delim:16}{keyn:>40}@{host[keyn]}')
        if host =={} and ip in software_list:
            print (f'{ip:88}{software_list[ip]}')

def runner():
    device_data=device_conn(*user_input()) # getting user input and providing that into connection function
    device_data_sorted = data_extract(*device_data) # extracting neccesry info from switch output
    graph_builder = graph_creator(**device_data_sorted) # building and showing a graph in the browser
    #software_ver_dict = software_ver(*device_data)
    #printing_output(neighbor_list_dict, software_ver_dict)

if __name__== "__main__":
    runner()
