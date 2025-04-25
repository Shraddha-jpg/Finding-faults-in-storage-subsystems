#Trial 1: With report formatting

import json
import os
import glob
from typing import Dict, List, Optional, Any
import re
from datetime import datetime
import requests
import base64

class PureRAGFaultDetector:
    def __init__(self, api_key=None):
        self.data_dirs = glob.glob("data_instance_*")
        self.api_key = api_key
        if not self.api_key:
            print("No Groq API key provided. For fault inference, please provide a Groq API key.")
            self.use_mock = True
        else:
            self.use_mock = False

    def _load_json_file(self, file_path: str) -> Any:
        """Load and return JSON file content."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None

    def _get_relevant_context(self, port: int, query: str) -> str:
        """Retrieve relevant context based on the query."""
        context_parts = []
        
        # Get system info
        system_file = f"data_instance_{port}/system.json"
        system_data = self._load_json_file(system_file)
        if system_data:
            if isinstance(system_data, list) and len(system_data) > 0:
                system_info = system_data[0]
            else:
                system_info = system_data
            context_parts.append(f"System Information:\n{json.dumps(system_info, indent=2)}")

        # Get latest metrics
        metrics_file = f"data_instance_{port}/system_metrics_{port}.json"
        metrics_data = self._load_json_file(metrics_file)
        if metrics_data and isinstance(metrics_data, list) and len(metrics_data) > 0:
            latest_metrics = metrics_data[-1]
            context_parts.append(f"Latest Metrics:\n{json.dumps(latest_metrics, indent=2)}")

        # Get volumes info
        volumes_file = f"data_instance_{port}/volume.json"
        volumes_data = self._load_json_file(volumes_file)
        if volumes_data:
            volumes = volumes_data if isinstance(volumes_data, list) else [volumes_data]
            context_parts.append(f"Volumes Information:\n{json.dumps(volumes, indent=2)}")

        # Get IO metrics for saturation calculation
        io_metrics_file = f"data_instance_{port}/io_metrics.json"
        io_metrics_data = self._load_json_file(io_metrics_file)
        if io_metrics_data:
            context_parts.append(f"IO Metrics:\n{json.dumps(io_metrics_data, indent=2)}")

        # Get replication metrics
        replication_file = f"data_instance_{port}/replication_metrics_{port}.json"
        replication_data = self._load_json_file(replication_file)
        if replication_data:
            context_parts.append(f"Replication Metrics:\n{json.dumps(replication_data, indent=2)}")

        # Get snapshots info
        snapshots_file = f"data_instance_{port}/snapshots.json"
        snapshots_data = self._load_json_file(snapshots_file)
        if snapshots_data:
            context_parts.append(f"Snapshots Information:\n{json.dumps(snapshots_data, indent=2)}")

        return "\n\n".join(context_parts)

    def _call_llm(self, context: str, query: str) -> str:
        
        """Call the Groq API with the given context and query."""
        if self.use_mock:
            return """
            {
                "fault_type": "Error analyzing faults",
                "details": {
                    "error": "No Groq API key provided. For fault inference, please provide a Groq API key."
                }
            }
            """
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            system_prompt = """You are a storage system fault detection expert. Analyze the provided system data and identify any faults.
            
            There are 3 types of faults:
            1. High latency due to high capacity
            2. High latency due to high saturation
            3. High latency due to replication link issues

            Analyze the systtem_metrics_<PORT>.json and look at the latest entry to infer the fault type for high capacity and high saturation.
            Analuse the replication_metrics_<PORT>.json to infer the fault type for replication link issues.
            
            For each fault type, follow these detection rules:
            
            For High latency due to high capacity:
            1. Check system_metrics_<PORT>.json and look at the latest entry
            2. If capacity_percentage exceeds 100% AND current latency exceeds 5ms, then there is a high latency due to high capacity
            3. The max_capacity can be inferred from system.json, the size of each volume can be inferred from volume.json
            4. Capacity contribution per volume = (Volume Size / Max Capacity) × 100
            5. Calculate volume_capacity as ((sum of size of all volumes)/max_capacity)*100, it can also be inferred from system_metrics_<PORT>.json
            6. Calculate snapshot_capacity as ((size of volume * snapshot_count)/max_capacity)*100 for each volume,it can also be inferred from system_metrics_<PORT>.json
            7. Total Capacity = Volume Capacity + Snapshot Capacity
            
            
            For High latency due to high saturation:
            1. Check system_metrics_<PORT>.json and look at the latest entry
            2. If saturation exceeds 100% AND current latency exceeds 5ms, then there is a high latency due to high saturation
            3. System Saturation = (Total Throughput / Max Throughput) × 100
            4. For each volume: Volume Throughput (MB/s) = (2000 IOPS × workload_size) / 1024, the workload size can be inferred from volume.json
            5. System saturation contribution per volume = (Volume Throughput / Max Throughput) × 100, max throughput can be inferred from system.json
            
            For High latency due to replication link issues:
            1. Check replication_metrics_<PORT>.json
            2. If latency exceeds 5ms for any replication link, then there is a high latency due to replication link issues
            3. For each affected volume, identify the source system, target system, and volume name
            
            Return ONLY a JSON object with the following structure including all the mentioned fields:
            {
                "fault_type": "High latency due to high capacity" or "High latency due to high saturation" or "High latency due to replication link issues" or "No fault",
                "details": {
                    "latency": <latency value>,
                    "capacity_percentage": <capacity percentage>,
                    "saturation": <system saturation percentage>,
                    "volume_capacity": <volume capacity percentage>,
                    "snapshot_capacity": <snapshot capacity percentage>,
                    "high_capacity_volumes": [
                        {
                            "volume_id": <volume id>,
                            "name": <volume name>,
                            "capacity_percentage": <capacity percentage>,
                            "size": <size>,
                            "snapshot_count": <snapshot count>
                        }
                    ],
                    "high_saturation_volumes": [
                        {
                            "volume_id": <volume id>,
                            "name": <volume name>,
                            "throughput": <throughput in MB/s>,
                            "saturation_contribution": <saturation contribution percentage>
                        }
                    ],
                    "snapshot_details": [
                        {
                            "volume_id": <volume id>,
                            "name": <volume name>,
                            "snapshot_count": <snapshot count>,
                            "capacity_contribution": <capacity contribution percentage>
                        }
                    ],
                    "replication_issues": [
                        {
                            "volume_id": <volume id>,
                            "volume_name": <volume name>,
                            "target_id": <target system id>,
                            "target_system_name": <target system name>,
                            "latency": <latency value>,
                            "timestamp": <timestamp>
                        }
                    ]
                }
            }
            
            If there are multiple faults, include details for each fault type in the response and give a detailed fault report for each type of fault.
            Constraint: Include the contribution of each volume in volume.json to the fault not just the highest one.
            example:If this my volume.json with x volumes:
                        [
                {
                    "id": "9b82e39a-8fd5-40b9-a2d7-c76ba020613c",
                    "name": "volume1",
                    "system_id": "61ed7a50-523c-469f-8424-ac4e31b841b3",
                    "size": 19,
                    "is_exported": false,
                    "exported_host_id": null,
                    "workload_size": 0,
                    "snapshot_settings": {
                        "79636e52-6c21-4783-826a-c4e57b3c9b0e": 10
                    },
                    "replication_settings": [],
                    "snapshot_frequencies": [
                        10
                    ],
                    "snapshot_count": 11
                },
                {
                    "id": "411c7c66-6982-4837-87d9-0c09f9e1107d",
                    "name": "volume2",
                    "system_id": "61ed7a50-523c-469f-8424-ac4e31b841b3",
                    "size": 5,
                    "is_exported": false,
                    "exported_host_id": null,
                    "workload_size": 0,
                    "snapshot_settings": {},
                    "replication_settings": []
                },
                {
                    "id": "9cfcf043-b0e3-4b12-8a46-ce4a4815ac10",
                    "name": "volume3",
                    "system_id": "61ed7a50-523c-469f-8424-ac4e31b841b3",
                    "size": 18,
                    "is_exported": false,
                    "exported_host_id": null,
                    "workload_size": 0,
                    "snapshot_settings": {},
                    "replication_settings": []
                }
            ]

            This is how I want the fault report to look like:
            Details of fault:
            Latency: 5.0ms
            Capacity percentage: 1255.0%
            Volume capacity: 42.0
            Snapshot capacity: 209.0

            - volume1 (ID: 9b82e39a-8fd5-40b9-a2d7-c76ba020613c):
            - Size: 19
            - Capacity contribution: 95.0%
            - volume3 (ID: 9cfcf043-b0e3-4b12-8a46-ce4a4815ac10):
            - Size: 18
            - Capacity contribution: 90.0%
            - volume2 (ID: 411c7c66-6982-4837-87d9-0c09f9e1107d):
            - Size: 5
            - Capacity contribution: 25.0%
            Snapshot capacity contributions:
            - Volume 9b82e39a-8fd5-40b9-a2d7-c76ba020613c:
            - Number of snapshots: 11
            - Capacity contribution: 1045.0%            
            
            For replication link issues, include the following details:
            The volume name, the latency and the source and target system names.
            If there are multiple faults, include details for each fault type in the response and give a detailed fault report for each type of fault.
            Example:
            If there are high latency due to high capacity and high latency due to high saturation and high latency due to replication link issues, include details for all faults in the response.
            If there are no faults, set fault_type to "No fault" and include the system metrics in the details.

            Begin the fault report by mentioning the system name.

            Don't repeat the fault report for each fault type, just give a detailed fault report just once for each type of fault.
            """
            
            data = {
                "model": "llama3-70b-8192",  # Using a Groq-supported model
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuery: {query}\n\nAnalyze the system data, identify faults, and provide a detailed report."}
                ],
                "temperature": 0.2,
                "max_tokens": 2000
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=data
            )
            

            if response.status_code == 200:
                result = response.json()
                response_text = result["choices"][0]["message"]["content"]
                
                #print(f"Raw Groq API response: {response_text}")
                # Extract JSON from the response
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    return json_match.group(0)
                else:
                    #print(f"Error: No JSON found in response: {response_text}")
                    print(f" No JSON found in response:\n {response_text}")
                    return """
                    {
                        "fault_type": "Error analyzing faults",
                        "details": {
                            "error": "Failed to extract JSON from LLM response"
                        }
                    }
                    """
            else:
                print(f"Error calling Groq API: {response.status_code} - {response.text}")
                return """
                {
                    "fault_type": "Error analyzing faults",
                    "details": {
                        "error": "Failed to call Groq API"
                    }
                }
                """
            
                
        except Exception as e:
            print(f"Exception calling Groq API: {str(e)}")
            return """
            {
                "fault_type": "Error analyzing faults",
                "details": {
                    "error": "Exception calling Groq API"
                }
            }
            """

    def detect_faults(self, query: str, port: Optional[int] = None) -> List[Dict]:
        """Detect faults using RAG and LLM."""
        faults = []
        ports_to_check = [port] if port else [int(d.split('_')[-1]) for d in self.data_dirs]

        for port in ports_to_check:
            # Get relevant context based on the query
            context = self._get_relevant_context(port, query)
            if not context:
                print(f"No data found for port {port}")
                continue

            # Call LLM with context and query
            llm_response = self._call_llm(context, query)
            
            try:
                # Parse LLM response
                fault_analysis = json.loads(llm_response)
                
                # Get system info
                system_file = f"data_instance_{port}/system.json"
                system_data = self._load_json_file(system_file)
                system_info = system_data[0] if isinstance(system_data, list) and len(system_data) > 0 else system_data
                
                # Add system info to fault
                fault_analysis['system_name'] = system_info.get('name', f'System_{port}')
                fault_analysis['port'] = port
                
                # Verify fault detection based on actual metrics
                if fault_analysis['fault_type'] != 'Error analyzing faults':
                    # Get latest metrics for verification
                    metrics_file = f"data_instance_{port}/system_metrics_{port}.json"
                    metrics_data = self._load_json_file(metrics_file)
                    if metrics_data and isinstance(metrics_data, list) and len(metrics_data) > 0:
                        latest_metrics = metrics_data[-1]
                        
                        # Extract actual values
                        current_latency = latest_metrics.get('current_latency', 0)
                        capacity_percentage = latest_metrics.get('capacity_percentage', 0)
                        saturation = latest_metrics.get('saturation', 0)
                        
                        # Verify high capacity fault
                        if fault_analysis['fault_type'] == 'High latency due to high capacity':
                            if capacity_percentage <= 100 or current_latency < 5:
                                fault_analysis['fault_type'] = 'No fault'
                                fault_analysis['details']['note'] = 'High capacity fault conditions not met'
                        
                        # Verify high saturation fault
                        elif fault_analysis['fault_type'] == 'High latency due to high saturation':
                            if saturation <= 100 or current_latency < 5:
                                fault_analysis['fault_type'] = 'No fault'
                                fault_analysis['details']['note'] = 'High saturation fault conditions not met'
                        
                        # Verify replication link issues
                        elif fault_analysis['fault_type'] == 'High latency due to replication link issues':
                            replication_file = f"data_instance_{port}/replication_metrics_{port}.json"
                            replication_data = self._load_json_file(replication_file)
                            
                            if replication_data:
                                has_replication_issue = False
                                for issue in replication_data:
                                    if issue.get('latency', 0) > 5:
                                        has_replication_issue = True
                                        break
                                
                                if not has_replication_issue:
                                    fault_analysis['fault_type'] = 'No fault'
                                    fault_analysis['details']['note'] = 'No replication link issues detected'
                
                faults.append(fault_analysis)
                
            except json.JSONDecodeError:
                print(f"Error parsing LLM response for port {port}: {llm_response}")
                # Create a basic fault report
                fault = {
                    'system_name': f'System_{port}',
                    'port': port,
                    'fault_type': 'Error analyzing faults',
                    'details': {
                        'error': 'Failed to parse LLM response'
                    }
                }
                faults.append(fault)

        return faults

    def format_fault_report(self, faults: List[Dict]) -> str:
        """Format the fault report in a readable way."""
        report = []
        for fault in faults:
            report.append(f"\nSystem: {fault['system_name']} (Port: {fault['port']})")
            report.append(f"Type of fault: {fault['fault_type']}")
            
            if fault['fault_type'] == 'High latency due to high capacity':
                details = fault['details']
                report.append("\nDetails of fault:")
                report.append(f"Latency: {details.get('latency', 'Unknown')}ms")
                report.append(f"Capacity percentage: {details.get('capacity_percentage', 'Unknown')}%")
                report.append(f"Volume capacity: {details.get('volume_capacity', 'Unknown')}")
                report.append(f"Snapshot capacity: {details.get('snapshot_capacity', 'Unknown')}")
                
                # Volume capacity details
                if details.get('high_capacity_volumes'):
                    report.append("\nVolumes causing high capacity:")
                    for vol in details['high_capacity_volumes']:
                        report.append(f"- {vol.get('name', 'Unknown')} (ID: {vol.get('volume_id', 'Unknown')}):")
                        report.append(f"  - Size: {vol.get('size', 'Unknown')}")
                        report.append(f"  - Capacity contribution: {vol.get('capacity_percentage', 'Unknown')}%")
                else:
                    report.append("\nNo volumes are contributing to high capacity.")
                
                # Snapshot capacity details
                if details.get('snapshot_details'):
                    report.append("\nSnapshot capacity contributions:")
                    for snap in details['snapshot_details']:
                        report.append(f"- Volume {snap.get('name', 'Unknown')} (ID: {snap.get('volume_id', 'Unknown')}):")
                        report.append(f"  - Number of snapshots: {snap.get('snapshot_count', 'Unknown')}")
                        report.append(f"  - Capacity contribution: {snap.get('capacity_contribution', 'Unknown')}%")
                else:
                    report.append("\nNo snapshot capacity contributions.")
            
            elif fault['fault_type'] == 'High latency due to high saturation':
                details = fault['details']
                report.append("\nDetails of fault:")
                report.append(f"Latency: {details.get('latency', 'Unknown')}ms")
                report.append(f"Saturation: {details.get('saturation', 'Unknown')}%")
                
                if details.get('high_saturation_volumes'):
                    report.append("\nVolumes contributing to high system saturation:")
                    for vol in details['high_saturation_volumes']:
                        report.append(
                            f"- {vol.get('name', 'Unknown')} (ID: {vol.get('volume_id', 'Unknown')}):\n"
                            f"  - Throughput: {vol.get('throughput', 'Unknown')} MB/s\n"
                            f"  - Saturation Contribution: {vol.get('saturation_contribution', 'Unknown')}%"
                        )
                else:
                    report.append("\nNo volumes are contributing to high saturation.")
            
            elif fault['fault_type'] == 'High latency due to replication link issues':
                details = fault['details']
                report.append("\nDetails of fault:")
                
                if details.get('replication_issues'):
                    report.append("\nReplication link issues:")
                    for issue in details['replication_issues']:
                        report.append(
                            f"Replication link: {fault['system_name']} to {issue['target_system_name']} "
                            f"for volume {issue['volume_name']} (ID: {issue['volume_id']})"
                        )
                        report.append(f"Latency due to replication link issue: {issue['latency']}ms")
                else:
                    report.append("\nNo replication link issues detected.")
            
            elif fault['fault_type'] == 'No fault':
                details = fault['details']
                report.append("\nNo faults detected in this system.")
                report.append(f"Current metrics:")
                report.append(f"- Latency: {details.get('latency', 'Unknown')}ms")
                report.append(f"- Capacity percentage: {details.get('capacity_percentage', 'Unknown')}%")
                report.append(f"- System Saturation: {details.get('saturation', 'Unknown')}%")
            
            elif fault['fault_type'] == 'Error analyzing faults':
                report.append("\nError analyzing faults:")
                report.append(f"- {fault['details'].get('error', 'Unknown error')}")
            
            report.append("\n" + "="*50)
        
        return "\n".join(report)

def main():
    # Hardcode your Groq API key here
    api_key = "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"  # Replace this with your actual Groq API key
    
    detector = PureRAGFaultDetector(api_key)
    
    print("Pure RAG-based Fault Detection System")
    print("Example queries:")
    print("- Show faults across all systems")
    print("- Show faults in system 5000")
    print("- Check replication issues in system 5001")
    print("- Analyze snapshot capacity in system 5000")
    print("\nType 'exit' to quit")
    
    while True:
        query = input("\nEnter your query: ").strip()
        if query.lower() == 'exit':
            break
            
        # Extract port from query if present
        port = None
        port_match = re.search(r'(?:system|port)\s+(\d+)', query.lower())
        if port_match:
            port = int(port_match.group(1))
        
        # Detect faults
        faults = detector.detect_faults(query, port)
        
        # Format and display report
        report = detector.format_fault_report(faults)
        #print("\nResponse:")
        #print(report)

if __name__ == "__main__":
    main()

#Trial 2.1: Raw response
'''
import json
import os
import glob
from typing import Dict, List, Optional, Any
import re
from datetime import datetime
import requests
import base64

class PureRAGFaultDetector:
    def __init__(self, api_key=None):
        self.data_dirs = glob.glob("data_instance_*")
        self.api_key = api_key
        if not self.api_key:
            print("No Groq API key provided. For fault inference, please provide a Groq API key.")
            self.use_mock = True
        else:
            self.use_mock = False

    def _load_json_file(self, file_path: str) -> Any:
        """Load and return JSON file content."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None

    def _get_relevant_context(self, port: int, query: str) -> str:
        """Retrieve relevant context based on the query."""
        context_parts = []
        
        # Get system info
        system_file = f"data_instance_{port}/system.json"
        system_data = self._load_json_file(system_file)
        if system_data:
            if isinstance(system_data, list) and len(system_data) > 0:
                system_info = system_data[0]
            else:
                system_info = system_data
            context_parts.append(f"System Information:\n{json.dumps(system_info, indent=2)}")

        # Get latest metrics
        metrics_file = f"data_instance_{port}/system_metrics_{port}.json"
        metrics_data = self._load_json_file(metrics_file)
        if metrics_data and isinstance(metrics_data, list) and len(metrics_data) > 0:
            latest_metrics = metrics_data[-1]
            context_parts.append(f"Latest Metrics:\n{json.dumps(latest_metrics, indent=2)}")

        # Get volumes info
        volumes_file = f"data_instance_{port}/volume.json"
        volumes_data = self._load_json_file(volumes_file)
        if volumes_data:
            volumes = volumes_data if isinstance(volumes_data, list) else [volumes_data]
            context_parts.append(f"Volumes Information:\n{json.dumps(volumes, indent=2)}")

        # Get IO metrics for saturation calculation
        io_metrics_file = f"data_instance_{port}/io_metrics.json"
        io_metrics_data = self._load_json_file(io_metrics_file)
        if io_metrics_data:
            context_parts.append(f"IO Metrics:\n{json.dumps(io_metrics_data, indent=2)}")

        # Get replication metrics
        replication_file = f"data_instance_{port}/replication_metrics_{port}.json"
        replication_data = self._load_json_file(replication_file)
        if replication_data:
            context_parts.append(f"Replication Metrics:\n{json.dumps(replication_data, indent=2)}")

        # Get snapshots info
        snapshots_file = f"data_instance_{port}/snapshots.json"
        snapshots_data = self._load_json_file(snapshots_file)
        if snapshots_data:
            context_parts.append(f"Snapshots Information:\n{json.dumps(snapshots_data, indent=2)}")

        return "\n\n".join(context_parts)

    def _call_llm(self, context: str, query: str) -> str:
        """Call the Groq API with the given context and query."""
        if self.use_mock:
            return """
            {
                "fault_type": "Error analyzing faults",
                "details": {
                    "error": "No Groq API key provided. For fault inference, please provide a Groq API key."
                }
            }
            """
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            system_prompt = """You are a storage system fault detection expert. Analyze the provided system data and identify any faults.
            
            There are 3 types of faults:
            1. High latency due to high capacity
            2. High latency due to high saturation
            3. High latency due to replication link issues
            
            For each fault type, follow these detection rules:
            
            For High latency due to high capacity:
            1. Check system_metrics_<PORT>.json and look at the latest entry
            2. If capacity_percentage exceeds 100% AND current latency exceeds 5ms, then there is a high latency due to high capacity
            3. The max_capacity can be inferred from system.json, the size of each volume can be inferred from volume.json
            4. Calculate volume_capacity as ((sum of size of all volumes)/max_capacity)*100, it can also be inferred from system_metrics_<PORT>.json
            5. Calculate snapshot_capacity as ((size of volume * snapshot_count)/max_capacity)*100 for each volume,it can also be inferred from system_metrics_<PORT>.json
            6. Total Capacity = Volume Capacity + Snapshot Capacity
            
            For High latency due to high saturation:
            1. Check system_metrics_<PORT>.json and look at the latest entry
            2. If saturation exceeds 100% AND current latency exceeds 5ms, then there is a high latency due to high saturation
            3. System Saturation = (Total Throughput / Max Throughput) × 100
            4. For each volume: Volume Throughput (MB/s) = (2000 IOPS × workload_size) / 1024
            5. System saturation contribution per volume = (Volume Throughput / Max Throughput) × 100
            
            For High latency due to replication link issues:
            1. Check replication_metrics_<PORT>.json
            2. If latency exceeds 5ms for any replication link, then there is a high latency due to replication link issues
            3. For each affected volume, identify the source system, target system, and volume name
            
            Return a JSON object with the following structure including all the mentioned fields:
            {
                "fault_type": "High latency due to high capacity" or "High latency due to high saturation" or "High latency due to replication link issues" or "No fault",
                "details": {
                    "latency": <latency value>,
                    "capacity_percentage": <capacity percentage>,
                    "saturation": <system saturation percentage>,
                    "volume_capacity": <volume capacity percentage>,
                    "snapshot_capacity": <snapshot capacity percentage>,
                    "high_capacity_volumes": [
                        {
                            "volume_id": <volume id>,
                            "name": <volume name>,
                            "capacity_percentage": <capacity percentage>,
                            "size": <size>,
                            "snapshot_count": <snapshot count>
                        }
                    ],
                    "high_saturation_volumes": [
                        {
                            "volume_id": <volume id>,
                            "name": <volume name>,
                            "throughput": <throughput in MB/s>,
                            "saturation_contribution": <saturation contribution percentage>
                        }
                    ],
                    "snapshot_details": [
                        {
                            "volume_id": <volume id>,
                            "name": <volume name>,
                            "snapshot_count": <snapshot count>,
                            "capacity_contribution": <capacity contribution percentage>
                        }
                    ],
                    "replication_issues": [
                        {
                            "volume_id": <volume id>,
                            "volume_name": <volume name>,
                            "target_id": <target system id>,
                            "target_system_name": <target system name>,
                            "latency": <latency value>,
                            "timestamp": <timestamp>
                        }
                    ]
                }
            }
            
            If there are multiple faults, include details for each fault type in the response and give a detailed fault report for each type of fault.
            Constraint: Include the contribution of each volume in volume.json to the fault not just the highest one.
            example:If this my volume.json with x volumes:
                        [
                {
                    "id": "9b82e39a-8fd5-40b9-a2d7-c76ba020613c",
                    "name": "volume1",
                    "system_id": "61ed7a50-523c-469f-8424-ac4e31b841b3",
                    "size": 19,
                    "is_exported": false,
                    "exported_host_id": null,
                    "workload_size": 0,
                    "snapshot_settings": {
                        "79636e52-6c21-4783-826a-c4e57b3c9b0e": 10
                    },
                    "replication_settings": [],
                    "snapshot_frequencies": [
                        10
                    ],
                    "snapshot_count": 11
                },
                {
                    "id": "411c7c66-6982-4837-87d9-0c09f9e1107d",
                    "name": "volume2",
                    "system_id": "61ed7a50-523c-469f-8424-ac4e31b841b3",
                    "size": 5,
                    "is_exported": false,
                    "exported_host_id": null,
                    "workload_size": 0,
                    "snapshot_settings": {},
                    "replication_settings": []
                },
                {
                    "id": "9cfcf043-b0e3-4b12-8a46-ce4a4815ac10",
                    "name": "volume3",
                    "system_id": "61ed7a50-523c-469f-8424-ac4e31b841b3",
                    "size": 18,
                    "is_exported": false,
                    "exported_host_id": null,
                    "workload_size": 0,
                    "snapshot_settings": {},
                    "replication_settings": []
                }
            ]

            This is how I want the fault report to look like:
            Details of fault:
            Latency: 5.0ms
            Capacity percentage: 1255.0%
            Volume capacity: 42.0
            Snapshot capacity: 209.0

            - volume1 (ID: 9b82e39a-8fd5-40b9-a2d7-c76ba020613c):
            - Size: 19
            - Capacity contribution: 95.0%
            - volume3 (ID: 9cfcf043-b0e3-4b12-8a46-ce4a4815ac10):
            - Size: 18
            - Capacity contribution: 90.0%
            - volume2 (ID: 411c7c66-6982-4837-87d9-0c09f9e1107d):
            - Size: 5
            - Capacity contribution: 25.0%
            Snapshot capacity contributions:
            - Volume 9b82e39a-8fd5-40b9-a2d7-c76ba020613c:
            - Number of snapshots: 11
            - Capacity contribution: 1045.0%            
            
            Capacity contribution per volume:(size of volume/max_capacity)*100
            For replication link issues, include the following details:
            The volume name, the latency and the source and target system names.
            If there are multiple faults, include details for each fault type in the response and give a detailed fault report for each type of fault.
            
            If there are high latency due to high capacity and high latency due to high saturation and high latency due to replication link issues, include details for all faults in the response.
            If there are no faults, set fault_type to "No fault" and include the system metrics in the details.
            """
            
            data = {
                "model": "llama3-70b-8192",  # Using a Groq-supported model
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuery: {query}\n\nAnalyze the system data, identify faults, and provide a detailed report."}
                ],
                "temperature": 0.2,
                "max_tokens": 2000
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=data
            )
            

            if response.status_code == 200:
                result = response.json()
                response_text = result["choices"][0]["message"]["content"]
                #print(f"Raw Groq API response: {response_text}")
                # Extract JSON from the response
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    return json_match.group(0)
                else:
                    print(f"Error: No JSON found in response: {response_text}")
                    return """
                    {
                        "fault_type": "Error analyzing faults",
                        "details": {
                            "error": "Failed to extract JSON from LLM response"
                        }
                    }
                    """
            else:
                print(f"Error calling Groq API: {response.status_code} - {response.text}")
                return """
                {
                    "fault_type": "Error analyzing faults",
                    "details": {
                        "error": "Failed to call Groq API"
                    }
                }
                """
                
        except Exception as e:
            print(f"Exception calling Groq API: {str(e)}")
            return """
            {
                "fault_type": "Error analyzing faults",
                "details": {
                    "error": "Exception calling Groq API"
                }
            }
            """

    def detect_faults(self, query: str, port: Optional[int] = None) -> List[Dict]:
        """Detect faults using RAG and LLM."""
        faults = []
        ports_to_check = [port] if port else [int(d.split('_')[-1]) for d in self.data_dirs]

        for port in ports_to_check:
            # Get relevant context based on the query
            context = self._get_relevant_context(port, query)
            if not context:
                print(f"No data found for port {port}")
                continue

            # Call LLM with context and query
            llm_response = self._call_llm(context, query)
            
            try:
                # Parse LLM response
                fault_analysis = json.loads(llm_response)
                
                # Get system info
                system_file = f"data_instance_{port}/system.json"
                system_data = self._load_json_file(system_file)
                system_info = system_data[0] if isinstance(system_data, list) and len(system_data) > 0 else system_data
                
                # Add system info to fault
                fault_analysis['system_name'] = system_info.get('name', f'System_{port}')
                fault_analysis['port'] = port
                
                # Verify fault detection based on actual metrics
                if fault_analysis['fault_type'] != 'Error analyzing faults':
                    # Get latest metrics for verification
                    metrics_file = f"data_instance_{port}/system_metrics_{port}.json"
                    metrics_data = self._load_json_file(metrics_file)
                    if metrics_data and isinstance(metrics_data, list) and len(metrics_data) > 0:
                        latest_metrics = metrics_data[-1]
                        
                        # Extract actual values
                        current_latency = latest_metrics.get('current_latency', 0)
                        capacity_percentage = latest_metrics.get('capacity_percentage', 0)
                        saturation = latest_metrics.get('saturation', 0)
                        
                        # Verify high capacity fault
                        if fault_analysis['fault_type'] == 'High latency due to high capacity':
                            if capacity_percentage <= 100 or current_latency < 5:
                                fault_analysis['fault_type'] = 'No fault'
                                fault_analysis['details']['note'] = 'High capacity fault conditions not met'
                        
                        # Verify high saturation fault
                        elif fault_analysis['fault_type'] == 'High latency due to high saturation':
                            if saturation <= 100 or current_latency < 5:
                                fault_analysis['fault_type'] = 'No fault'
                                fault_analysis['details']['note'] = 'High saturation fault conditions not met'
                        
                        # Verify replication link issues
                        elif fault_analysis['fault_type'] == 'High latency due to replication link issues':
                            replication_file = f"data_instance_{port}/replication_metrics_{port}.json"
                            replication_data = self._load_json_file(replication_file)
                            
                            if replication_data:
                                has_replication_issue = False
                                for issue in replication_data:
                                    if issue.get('latency', 0) > 5:
                                        has_replication_issue = True
                                        break
                                
                                if not has_replication_issue:
                                    fault_analysis['fault_type'] = 'No fault'
                                    fault_analysis['details']['note'] = 'No replication link issues detected'
                
                faults.append(fault_analysis)
                
            except json.JSONDecodeError:
                print(f"Error parsing LLM response for port {port}: {llm_response}")
                # Create a basic fault report
                fault = {
                    'system_name': f'System_{port}',
                    'port': port,
                    'fault_type': 'Error analyzing faults',
                    'details': {
                        'error': 'Failed to parse LLM response'
                    }
                }
                faults.append(fault)

        return faults

def main():
    # Hardcode your Groq API key here
    api_key = "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"  # Replace this with your actual Groq API key
    
    detector = PureRAGFaultDetector(api_key)
    
    print("Pure RAG-based Fault Detection System")
    print("Example queries:")
    print("- Show faults across all systems")
    print("- Show faults in system 5000")
    print("- Check replication issues in system 5001")
    print("- Analyze snapshot capacity in system 5000")
    print("\nType 'exit' to quit")
    
    while True:
        query = input("\nEnter your query: ").strip()
        if query.lower() == 'exit':
            break
            
        # Extract port from query if present
        port = None
        port_match = re.search(r'(?:system|port)\s+(\d+)', query.lower())
        if port_match:
            port = int(port_match.group(1))
        
        # Detect faults
        faults = detector.detect_faults(query, port)
        
        # Print the raw LLM response
        print("\nResponse:")
        print(json.dumps(faults, indent=2))

if __name__ == "__main__":
    main()
'''
'''
#Trial 2.2: Formatting 2.1 properly
import json
import os
import glob
from typing import Dict, List, Optional, Any
import re
from datetime import datetime
import requests
import base64

class PureRAGFaultDetector:
    def __init__(self, api_key=None):
        self.data_dirs = glob.glob("data_instance_*")
        self.api_key = api_key
        if not self.api_key:
            print("No Groq API key provided. For fault inference, please provide a Groq API key.")
            self.use_mock = True
        else:
            self.use_mock = False

    def _load_json_file(self, file_path: str) -> Any:
        """Load and return JSON file content."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None

    def _get_relevant_context(self, port: int, query: str) -> str:
        """Retrieve relevant context based on the query."""
        context_parts = []
        
        # Get system info
        system_file = f"data_instance_{port}/system.json"
        system_data = self._load_json_file(system_file)
        if system_data:
            if isinstance(system_data, list) and len(system_data) > 0:
                system_info = system_data[0]
            else:
                system_info = system_data
            context_parts.append(f"System Information:\n{json.dumps(system_info, indent=2)}")

        # Get latest metrics
        metrics_file = f"data_instance_{port}/system_metrics_{port}.json"
        metrics_data = self._load_json_file(metrics_file)
        if metrics_data and isinstance(metrics_data, list) and len(metrics_data) > 0:
            latest_metrics = metrics_data[-1]
            context_parts.append(f"Latest Metrics:\n{json.dumps(latest_metrics, indent=2)}")

        # Get volumes info
        volumes_file = f"data_instance_{port}/volume.json"
        volumes_data = self._load_json_file(volumes_file)
        if volumes_data:
            volumes = volumes_data if isinstance(volumes_data, list) else [volumes_data]
            context_parts.append(f"Volumes Information:\n{json.dumps(volumes, indent=2)}")

        # Get IO metrics for saturation calculation
        io_metrics_file = f"data_instance_{port}/io_metrics.json"
        io_metrics_data = self._load_json_file(io_metrics_file)
        if io_metrics_data:
            context_parts.append(f"IO Metrics:\n{json.dumps(io_metrics_data, indent=2)}")

        # Get replication metrics
        replication_file = f"data_instance_{port}/replication_metrics_{port}.json"
        replication_data = self._load_json_file(replication_file)
        if replication_data:
            context_parts.append(f"Replication Metrics:\n{json.dumps(replication_data, indent=2)}")

        # Get snapshots info
        snapshots_file = f"data_instance_{port}/snapshots.json"
        snapshots_data = self._load_json_file(snapshots_file)
        if snapshots_data:
            context_parts.append(f"Snapshots Information:\n{json.dumps(snapshots_data, indent=2)}")

        context = "\n\n".join(context_parts)
        print(f"Context sent to Groq API for port {port}:\n{context}")
        return context

    def _call_llm(self, context: str, query: str, retry_count: int = 0, max_retries: int = 2) -> str:
        """Call the Groq API with the given context and query."""
        if self.use_mock:
            return """
            {
                "fault_type": "Error analyzing faults",
                "details": {
                    "error": "No Groq API key provided. For fault inference, please provide a Groq API key."
                }
            }
            """
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            system_prompt = """You are a storage system fault detection expert. Analyze the provided system data and identify any faults. Return ONLY a JSON object or array of JSON objects as specified below, with NO additional text, narrative, or explanations outside the JSON structure.

            There are 3 types of faults:
            1. High latency due to high capacity
            2. High latency due to high saturation
            3. High latency due to replication link issues
            
            For each fault type, follow these detection rules:
            
            For High latency due to high capacity:
            1. Check system_metrics_<PORT>.json and look at the latest entry
            2. If capacity_percentage exceeds 100% AND current_latency exceeds 5ms, then there is a high latency due to high capacity
            3. Calculate volume_capacity as ((sum of size of all volumes)/max_capacity)*100
            4. Calculate snapshot_capacity as ((size of volume * snapshot_count)/max_capacity)*100 for each volume, summed across all volumes
            5. Total Capacity = Volume Capacity + Snapshot Capacity
            6. If max_capacity is missing, set volume_capacity and snapshot_capacity to 0.0 and include a note in details: {"note": "Missing max_capacity for capacity calculations"}
            7. If no snapshots exist, set snapshot_capacity to 0.0 and snapshot_details to []
            
            For High latency due to high saturation:
            1. Check system_metrics_<PORT>.json and look at the latest entry
            2. If saturation exceeds 100% AND current_latency exceeds 5ms, then there is a high latency due to high saturation
            3. System Saturation = (Total Throughput / Max Throughput) × 100
            4. For each volume: Volume Throughput (MB/s) = (2000 IOPS × workload_size) / 1024
            5. System saturation contribution per volume = (Volume Throughput / Max Throughput) × 100
            6. If saturation data is missing, set saturation to 0.0 and high_saturation_volumes to []
            
            For High latency due to replication link issues:
            1. Check replication_metrics_<PORT>.json
            2. If latency exceeds 5ms for any replication link, then there is a high latency due to replication link issues
            3. For each affected volume, include volume_id, volume_name, target_id, target_system_name, latency, and timestamp
            4. If no replication data exists, set replication_issues to []
            
            Response Structure:
            - For queries like "describe each fault" or "fault report for each fault", return an array of JSON objects, one for each detected fault type, even if only one fault exists.
            - For other queries, return a single JSON object with the most relevant fault or "No fault" if none are detected.
            - Each JSON object must have the following structure:
            {
                "fault_type": "High latency due to high capacity" or "High latency due to high saturation" or "High latency due to replication link issues" or "No fault",
                "details": {
                    "latency": <float, latest current_latency or 0.0 if missing>,
                    "capacity_percentage": <float, from system_metrics or 0.0 if missing>,
                    "saturation": <float, from system_metrics or 0.0 if missing>,
                    "volume_capacity": <float, calculated or 0.0 if missing>,
                    "snapshot_capacity": <float, calculated or 0.0 if missing>,
                    "high_capacity_volumes": [
                        {
                            "volume_id": <string>,
                            "name": <string>,
                            "capacity_percentage": <float, (size/max_capacity)*100>,
                            "size": <int>,
                            "snapshot_count": <int>
                        }
                    ],
                    "high_saturation_volumes": [
                        {
                            "volume_id": <string>,
                            "name": <string>,
                            "throughput": <float, in MB/s>,
                            "saturation_contribution": <float, percentage>
                        }
                    ],
                    "snapshot_details": [
                        {
                            "volume_id": <string>,
                            "name": <string>,
                            "snapshot_count": <int>,
                            "capacity_contribution": <float, (size*snapshot_count/max_capacity)*100>
                        }
                    ],
                    "replication_issues": [
                        {
                            "volume_id": <string>,
                            "volume_name": <string>,
                            "target_id": <string>,
                            "target_system_name": <string>,
                            "latency": <float>,
                            "timestamp": <string, ISO format>
                        }
                    ]
                }
            }
            
            Constraints:
            - Include ALL fields in the details dictionary, even if they are 0.0 or empty arrays.
            - Include the contribution of each volume in volume.json to the fault, not just the highest one.
            - If max_capacity is missing, set volume_capacity and snapshot_capacity to 0.0 and include a note.
            - If no faults are detected, return a single object with "fault_type": "No fault" and include system metrics.
            - For queries requesting "each fault", return an array of objects, one per fault type detected.
            
            Example:
            If volume.json has:
            [
                {
                    "id": "9b82e39a-8fd5-40b9-a2d7-c76ba020613c",
                    "name": "volume1",
                    "size": 19,
                    "snapshot_count": 11
                },
                {
                    "id": "411c7c66-6982-4837-87d9-0c09f9e1107d",
                    "name": "volume2",
                    "size": 5,
                    "snapshot_count": 0
                }
            ]
            And max_capacity is 20, system_metrics shows capacity_percentage=210%, saturation=150%, current_latency=13ms, and replication_metrics shows one issue with latency=8ms:
            For query "describe each fault":
            [
                {
                    "fault_type": "High latency due to high capacity",
                    "details": {
                        "latency": 13.0,
                        "capacity_percentage": 210.0,
                        "saturation": 150.0,
                        "volume_capacity": 120.0,
                        "snapshot_capacity": 1045.0,
                        "high_capacity_volumes": [
                            {
                                "volume_id": "9b82e39a-8fd5-40b9-a2d7-c76ba020613c",
                                "name": "volume1",
                                "capacity_percentage": 95.0,
                                "size": 19,
                                "snapshot_count": 11
                            },
                            {
                                "volume_id": "411c7c66-6982-4837-87d9-0c09f9e1107d",
                                "name": "volume2",
                                "capacity_percentage": 25.0,
                                "size": 5,
                                "snapshot_count": 0
                            }
                        ],
                        "high_saturation_volumes": [],
                        "snapshot_details": [
                            {
                                "volume_id": "9b82e39a-8fd5-40b9-a2d7-c76ba020613c",
                                "name": "volume1",
                                "snapshot_count": 11,
                                "capacity_contribution": 1045.0
                            }
                        ],
                        "replication_issues": []
                    }
                },
                {
                    "fault_type": "High latency due to high saturation",
                    "details": {
                        "latency": 13.0,
                        "capacity_percentage": 210.0,
                        "saturation": 150.0,
                        "volume_capacity": 120.0,
                        "snapshot_capacity": 1045.0,
                        "high_capacity_volumes": [],
                        "high_saturation_volumes": [
                            {
                                "volume_id": "9b82e39a-8fd5-40b9-a2d7-c76ba020613c",
                                "name": "volume1",
                                "throughput": 50.0,
                                "saturation_contribution": 100.0
                            }
                        ],
                        "snapshot_details": [],
                        "replication_issues": []
                    }
                },
                {
                    "fault_type": "High latency due to replication link issues",
                    "details": {
                        "latency": 13.0,
                        "capacity_percentage": 210.0,
                        "saturation": 150.0,
                        "volume_capacity": 120.0,
                        "snapshot_capacity": 1045.0,
                        "high_capacity_volumes": [],
                        "high_saturation_volumes": [],
                        "snapshot_details": [],
                        "replication_issues": [
                            {
                                "volume_id": "411c7c66-6982-4837-87d9-0c09f9e1107d",
                                "volume_name": "volume2",
                                "target_id": "some-target-id",
                                "target_system_name": "System 5001",
                                "latency": 8.0,
                                "timestamp": "2025-04-19T12:00:00"
                            }
                        ]
                    }
                }
            ]
            """
            
            data = {
                "model": "llama3-70b-8192",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuery: {query}\n\nAnalyze the system data, identify faults, and provide a detailed report in JSON format only."}
                ],
                "temperature": 0.2,
                "max_tokens": 3000
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=data
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result["choices"][0]["message"]["content"]
                print(f"Raw Groq API response: {response_text}")
                # Extract JSON from the response
                json_match = re.search(r'\s*(\[.*?\]|\{.*?\})\s*', response_text, re.DOTALL)
                if json_match:
                    return json_match.group(1)
                elif retry_count < max_retries:
                    print(f"Retrying ({retry_count + 1}/{max_retries}) due to non-JSON response")
                    # Retry with a stricter prompt
                    data["messages"][1]["content"] = (
                        f"Context:\n{context}\n\nQuery: {query}\n\n"
                        "Previous response was not JSON. Return ONLY a JSON object or array as specified, with no narrative text."
                    )
                    return self._call_llm(context, query, retry_count + 1, max_retries)
                else:
                    print(f"Error: No JSON found in response after {max_retries} retries: {response_text}")
                    return """
                    {
                        "fault_type": "Error analyzing faults",
                        "details": {
                            "error": "Failed to extract JSON from LLM response"
                        }
                    }
                    """
            else:
                print(f"Error calling Groq API: {response.status_code} - {response.text}")
                return """
                {
                    "fault_type": "Error analyzing faults",
                    "details": {
                        "error": "Failed to call Groq API"
                    }
                }
                """
                
        except Exception as e:
            print(f"Exception calling Groq API: {str(e)}")
            return """
            {
                "fault_type": "Error analyzing faults",
                "details": {
                    "error": "Exception calling Groq API"
                }
            }
            """

    def detect_faults(self, query: str, port: Optional[int] = None) -> List[Dict]:
        """Detect faults using RAG and LLM."""
        faults = []
        ports_to_check = [port] if port else [int(d.split('_')[-1]) for d in self.data_dirs]

        for port in ports_to_check:
            # Get relevant context based on the query
            context = self._get_relevant_context(port, query)
            if not context:
                print(f"No data found for port {port}")
                continue

            # Call LLM with context and query
            llm_response = self._call_llm(context, query)
            
            try:
                # Parse LLM response
                fault_analysis = json.loads(llm_response)
                
                # Get system info
                system_file = f"data_instance_{port}/system.json"
                system_data = self._load_json_file(system_file)
                system_info = system_data[0] if isinstance(system_data, list) and len(system_data) > 0 else system_data
                
                # Normalize response to always be a list
                if isinstance(fault_analysis, dict):
                    fault_list = [fault_analysis]
                else:
                    fault_list = fault_analysis
                
                # Split "Multiple faults" into separate fault objects
                normalized_faults = []
                for fault in fault_list:
                    if fault.get('fault_type') == 'Multiple faults':
                        details = fault.get('details', {})
                        # High capacity fault
                        if details.get('capacity_percentage', 0) > 100 and details.get('latency', 0) > 5:
                            normalized_faults.append({
                                'fault_type': 'High latency due to high capacity',
                                'details': {
                                    'latency': details.get('latency', 0.0),
                                    'capacity_percentage': details.get('capacity_percentage', 0.0),
                                    'saturation': details.get('saturation', 0.0),
                                    'volume_capacity': details.get('volume_capacity', 0.0),
                                    'snapshot_capacity': details.get('snapshot_capacity', 0.0),
                                    'high_capacity_volumes': details.get('high_capacity_volumes', []),
                                    'high_saturation_volumes': [],
                                    'snapshot_details': details.get('snapshot_details', []),
                                    'replication_issues': []
                                }
                            })
                        # High saturation fault
                        if details.get('saturation', 0) > 100 and details.get('latency', 0) > 5:
                            normalized_faults.append({
                                'fault_type': 'High latency due to high saturation',
                                'details': {
                                    'latency': details.get('latency', 0.0),
                                    'capacity_percentage': details.get('capacity_percentage', 0.0),
                                    'saturation': details.get('saturation', 0.0),
                                    'volume_capacity': details.get('volume_capacity', 0.0),
                                    'snapshot_capacity': details.get('snapshot_capacity', 0.0),
                                    'high_capacity_volumes': [],
                                    'high_saturation_volumes': details.get('high_saturation_volumes', []),
                                    'snapshot_details': details.get('snapshot_details', []),
                                    'replication_issues': []
                                }
                            })
                        # Replication issues
                        if details.get('replication_issues'):
                            normalized_faults.append({
                                'fault_type': 'High latency due to replication link issues',
                                'details': {
                                    'latency': details.get('latency', 0.0),
                                    'capacity_percentage': details.get('capacity_percentage', 0.0),
                                    'saturation': details.get('saturation', 0.0),
                                    'volume_capacity': details.get('volume_capacity', 0.0),
                                    'snapshot_capacity': details.get('snapshot_capacity', 0.0),
                                    'high_capacity_volumes': [],
                                    'high_saturation_volumes': [],
                                    'snapshot_details': details.get('snapshot_details', []),
                                    'replication_issues': details.get('replication_issues', [])
                                }
                            })
                    else:
                        normalized_faults.append(fault)
                
                # Add fallback calculations for volume_capacity and snapshot_capacity
                for fault in normalized_faults:
                    if fault['fault_type'] != 'Error analyzing faults':
                        volumes_file = f"data_instance_{port}/volume.json"
                        volumes_data = self._load_json_file(volumes_file)
                        if volumes_data and system_data:
                            max_capacity = system_data.get('max_capacity', 0)
                            if max_capacity == 0:
                                fault['details']['note'] = "Missing max_capacity for capacity calculations"
                                fault['details']['volume_capacity'] = 0.0
                                fault['details']['snapshot_capacity'] = 0.0
                            else:
                                total_volume_size = sum(vol.get('size', 0) for vol in volumes_data)
                                total_snapshot_capacity = sum(vol.get('size', 0) * vol.get('snapshot_count', 0) for vol in volumes_data)
                                fault['details']['volume_capacity'] = (total_volume_size / max_capacity) * 100 if max_capacity else 0.0
                                fault['details']['snapshot_capacity'] = (total_snapshot_capacity / max_capacity) * 100 if max_capacity else 0.0
                        
                        # Ensure all required fields are present
                        fault['details'].setdefault('latency', 0.0)
                        fault['details'].setdefault('capacity_percentage', 0.0)
                        fault['details'].setdefault('saturation', 0.0)
                        fault['details'].setdefault('volume_capacity', 0.0)
                        fault['details'].setdefault('snapshot_capacity', 0.0)
                        fault['details'].setdefault('high_capacity_volumes', [])
                        fault['details'].setdefault('high_saturation_volumes', [])
                        fault['details'].setdefault('snapshot_details', [])
                        fault['details'].setdefault('replication_issues', [])
                
                # Add system info to each fault
                for fault in normalized_faults:
                    fault['system_name'] = system_info.get('name', f'System_{port}')
                    fault['port'] = port
                
                # Verify fault detection based on actual metrics
                metrics_file = f"data_instance_{port}/system_metrics_{port}.json"
                metrics_data = self._load_json_file(metrics_file)
                if metrics_data and isinstance(metrics_data, list) and len(metrics_data) > 0:
                    latest_metrics = metrics_data[-1]
                    current_latency = latest_metrics.get('current_latency', 0)
                    capacity_percentage = latest_metrics.get('capacity_percentage', 0)
                    saturation = latest_metrics.get('saturation', 0)
                    
                    for fault in normalized_faults:
                        if fault['fault_type'] == 'High latency due to high capacity':
                            if capacity_percentage <= 100 or current_latency < 5:
                                fault['fault_type'] = 'No fault'
                                fault['details']['note'] = 'High capacity fault conditions not met'
                        elif fault['fault_type'] == 'High latency due to high saturation':
                            if saturation <= 100 or current_latency < 5:
                                fault['fault_type'] = 'No fault'
                                fault['details']['note'] = 'High saturation fault conditions not met'
                        elif fault['fault_type'] == 'High latency due to replication link issues':
                            replication_file = f"data_instance_{port}/replication_metrics_{port}.json"
                            replication_data = self._load_json_file(replication_file)
                            if replication_data:
                                has_replication_issue = False
                                for issue in replication_data:
                                    if issue.get('latency', 0) > 5:
                                        has_replication_issue = True
                                        break
                                if not has_replication_issue:
                                    fault['fault_type'] = 'No fault'
                                    fault['details']['note'] = 'No replication link issues detected'
                
                faults.extend(normalized_faults)
                
            except json.JSONDecodeError:
                print(f"Error parsing LLM response for port {port}: {llm_response}")
                fault = {
                    'system_name': f'System_{port}',
                    'port': port,
                    'fault_type': 'Error analyzing faults',
                    'details': {
                        'error': 'Failed to parse LLM response'
                    }
                }
                faults.append(fault)

        return faults

def main():
    # Hardcode your Groq API key here
    api_key = ""
    
    detector = PureRAGFaultDetector(api_key)
    
    print("Pure RAG-based Fault Detection System")
    print("Example queries:")
    print("- Show faults across all systems")
    print("- Show faults in system 5000")
    print("- Check replication issues in system 5001")
    print("- Analyze snapshot capacity in system 5000")
    print("\nType 'exit' to quit")
    
    while True:
        query = input("\nEnter your query: ").strip()
        if query.lower() == 'exit':
            break
            
        # Extract port from query if present
        port = None
        port_match = re.search(r'(?:system|port)\s+(\d+)', query.lower())
        if port_match:
            port = int(port_match.group(1))
        
        # Detect faults
        faults = detector.detect_faults(query, port)
        
        # Print the raw LLM response
        print("\nResponse:")
        print(json.dumps(faults, indent=2))

if __name__ == "__main__":
    main()
    '''
