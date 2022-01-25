import requests, re, os, urllib3, json
from pprint import pprint
from unidecode import unidecode
from ansible.plugins.inventory import BaseInventoryPlugin


ANSIBLE_METADATA = {
    'metadata_version': '0.1.0',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: librenms_inventory
plugin_type: inventory
short_description: Use LibreNMS as invenroty for ansible
version_added: "2.9.10"
description:
        - "A very simple Inventory Plugin created for demonstration purposes only."
options:
author:
    - Wouter Wolkers
'''


#variables
exclude_disabled = True
regex_ignore_case = True
re_flags = re.IGNORECASE
validate_certs = False

libre_to_ansible_variable_mapping = { #map certain variable names to ansible names
    'hostname': 'ansible_host',
    'os': 'ansible_network_os'
}
libre_to_ansible_os_mapping = {
    'asa': 'asa',
    'ios':'ios',
    'iosxe':'ios' }

output = {
    '_meta': {
        'hostvars': {
        }
    },
    'all': {
        'hosts': [],
        'vars': {}
    }
}

#functions
def _http_request(url):
    r = requests.get(url, headers=headers, verify=validate_certs)
    if r.json()['status'] == "error":
        #libre returns error if there is zero devices in the group. WTF? Here is workaround:
        if "No devices found in group" in r.json()['message']:
            return dict()
        else:
            raise AnsibleError(r.json()['message'])
    return r.json()

def _filter_device_groups(device_groups, filters):
    result = list()
    for f in filters:
        result += [ grp for grp in device_groups['groups'] if re.match(f, grp['name'], re_flags)  ]
    return result

def _get_devices_from_group(device_group):
    url = args.libre_api_url+'/devicegroups/'+device_group['name']
    response = _http_request(url)
    return response.get('devices', list())

def _gen_groups_for_ansible(groups, aGroups=None, parentGroup=None):
    if aGroups is None: aGroups = dict()
    for g in groups:
        aGroups.setdefault(g['name'], { 'children': [], 'hosts': [] })
        if parentGroup:
            aGroups[parentGroup]['children'].append(g['name'])
        if 'childContainerIdList' in g:
            genGroupsForAnsible(g['childContainerIdList'], aGroups, g['name'])
    return aGroups

def _get_device_by_id(device_id):
    url = args.libre_api_url+'/devices/'+str(device_id)
    device = _http_request(url)
    return device['devices'][0]

def _add_group(group_name, output):
    output.update({group_name: { 'children': [], 'hosts': [] } })

def _add_device(device, group_name, output):
    if len(device['sysName']):
        hostname = unidecode(device['sysName'])
    else:
        hostname = device['hostname']
    hostVars = {}
    if not (device['disabled'] > 0 and exclude_disabled) or (device['disabled'] == 0):
        for property_name, value in device.items(): #modify host variables according to the map
            new_property_name = 'libre_'+property_name
            new_property_name = libre_to_ansible_variable_mapping.get(property_name, new_property_name)
            if new_property_name == 'ansible_network_os':
                value = libre_to_ansible_os_mapping.get(value, value)
            hostVars.update({new_property_name: value})

        output['_meta']['hostvars'][hostname] = hostVars
        output['all']['hosts'].append(hostname)
        output.setdefault( group_name, { 'hosts': list() } ) #create device group if it does not exist
        output[group_name]['hosts'].append( hostname ) #add current device to the group


librenms_hostname = 'https://librenms.org'
librenms_auth_token = 'yourapikeyhere'
headers = {
        'X-Auth-Token': librenms_auth_token,
        }
                

class InventoryModule(BaseInventoryPlugin):
    """read hosts from LibreNMS"""

    NAME = 'wwolkers.librenms_inventory.librenms_inventory'

    def verify_file(self, path):
        """Verify that the source file can be processed correctly.

        Parameters:
            path:AnyStr The path to the file that needs to be verified

        Returns:
            bool True if the file is valid, else False
        """
        #no files, just API
        return True
    def _get_librenms_host_data(self):
        """Get the data from LibreNMS
        
        Returns:
            dict The host data formatted as expected for an Inventory Script
        """
        #process cli args and env variables
#        parser = configargparse.ArgParser()
#        parser.add_argument("--libre-api-url", env_var='LIBRENMS_API_URL', help="api endpoint of LibreNMS", required=True)
#        parser.add_argument("--libre-api-token", env_var='LIBRENMS_TOKEN', help="auth token for LibreNMS", required=True)
#        parser.add_argument("--group-names-regex", env_var='LIBRE_GROUP_NAMES_REGEX', help="LibreNMS device group names regex filter. --group-names \"group1\" \"group2\" ", required=True, nargs='+')
#        parser.add_argument("--include-ip", help="include IP in yml output", action="store_true")
#        parser.add_argument("--list", help="list hosts", action="store_true")
#        args = parser.parse_args()
#        devGroup = args.group_names_regex
#        headers = { 'X-Auth-Token': args.libre_api_token }


        if not validate_certs:
            urllib3.disable_warnings()
        #get device groups
        url = librenms_hostname+'/api/v0/devicegroups'
        all_device_groups = _http_request(url)
        device_groups = _filter_device_groups(all_device_groups, args.group_names_regex)

        #get devices from groups
        devices = list()
        for grp in device_groups:
            _add_group(grp['name'], output)
            device_ids_dict = _get_devices_from_group(grp)
        for device_id_dict in device_ids_dict:
            tmp_dev = _get_device_by_id(device_id_dict['device_id'])
            _add_device(tmp_dev, grp['name'], output)

        jout = json.dumps(output, indent=4, sort_keys=True)
        return(jout) 

    def parse(self, inventory, loader, path, cache=True):
        """Parse and populate the inventory with data about hosts.

        Parameters:
            inventory The inventory to populate
        """
        # call base method to ensure properties are available for use with other helper methods
        super(InventoryModule, self).parse(inventory, loader, path, cache)

        raw_data = self._get_librenms_host_data()
        _meta = raw_data.pop('_meta')
        for group_name, group_data in raw_data.items():
            for host_name in group_data['hosts']:
                self.inventory.add_host(host_name)
                for var_key, var_val in _meta['hostvars'][host_name].items():
                    self.inventory.set_variable(host_name, var_key, var_val)
