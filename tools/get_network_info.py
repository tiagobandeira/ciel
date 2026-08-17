"""
Tool para coletar informações de rede, incluindo IP, interfaces e redes WiFi disponíveis.
"""
import subprocess
import platform

def run():
    results = {}
    try:
        # IP e Conexão Atual
        if platform.system() == "Windows":
            ip_output = subprocess.check_output("ipconfig", shell=True).decode('cp1252')
            results['network_config'] = ip_output
            
            # WiFi Disponíveis
            wifi_output = subprocess.check_output("netsh wlan show networks", shell=True).decode('cp1252')
            results['available_wifis'] = wifi_output
        else:
            ip_output = subprocess.check_output("ifconfig || ip addr", shell=True).decode()
            results['network_config'] = ip_output
            wifi_output = subprocess.check_output("nmcli dev wifi", shell=True).decode()
            results['available_wifis'] = wifi_output
            
    except Exception as e:
        return f"Erro ao coletar dados de rede: {str(e)}"
    
    return results