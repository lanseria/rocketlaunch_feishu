import lark_oapi as lark
from lark_oapi.api.bitable.v1 import UpdateAppTableRecordRequest, AppTableRecord, CreateAppTableRecordRequest
from lark_oapi.api.contact.v3 import *
from dotenv import load_dotenv
import os
import json
import logging

# Set up logger
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO) # Level set by main cli.py
# handler = logging.StreamHandler() # Handler configured by main cli.py
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# handler.setFormatter(formatter)
# logger.addHandler(handler)

class FeishuBitableHelper:
    def __init__(self):
        load_dotenv()
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")
        if not app_id or not app_secret:
            raise ValueError("请在.env文件中配置FEISHU_APP_ID和FEISHU_APP_SECRET")
        
        log_level_str = os.getenv("LARK_LOG_LEVEL", "INFO").upper()
        lark_log_level = getattr(lark.LogLevel, log_level_str, lark.LogLevel.INFO)

        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark_log_level) \
            .build()
            
        self.app_token = os.getenv("BITABLE_APP_TOKEN")
        self.table_id = os.getenv("BITABLE_TABLE_ID")
        self.view_id = os.getenv("BITABLE_VIEW_ID")

        if not self.app_token or not self.table_id:
            raise ValueError("请在.env文件中配置BITABLE_APP_TOKEN和BITABLE_TABLE_ID")


    def list_records(self, field_names=None, sort=None, filter=None, page_size=100):
        from lark_oapi.api.bitable.v1 import SearchAppTableRecordRequest, SearchAppTableRecordRequestBody, Sort, FilterInfo, Condition

        request_body_builder = SearchAppTableRecordRequestBody.builder()

        if self.view_id:
            request_body_builder = request_body_builder.view_id(self.view_id)

        if field_names:
            request_body_builder = request_body_builder.field_names(field_names)

        if sort:
            sort_list = []
            for s in sort:
                sort_obj = Sort.builder() \
                    .field_name(s.get("field_name")) \
                    .desc(s.get("desc", False)) \
                    .build()
                sort_list.append(sort_obj)
            request_body_builder = request_body_builder.sort(sort_list)
        
        if filter:
            conditions = []
            for f_cond in filter.get("conditions", []): # Renamed f to f_cond
                condition = Condition.builder() \
                    .field_name(f_cond.get("field_name")) \
                    .operator(f_cond.get("operator")) \
                    .value(f_cond.get("value")) \
                    .build()
                conditions.append(condition)
            
            filter_info = FilterInfo.builder() \
                .conjunction(filter.get("conjunction", "and")) \
                .conditions(conditions) \
                .build()
            request_body_builder = request_body_builder.filter(filter_info)

        request_body = request_body_builder.automatic_fields(False).build()
        
        all_records = []
        page_token = None
        while True:
            request_builder = SearchAppTableRecordRequest.builder() \
                .app_token(self.app_token) \
                .table_id(self.table_id) \
                .page_size(min(page_size, 500)) # Max page_size is 500 for search
            
            if page_token:
                request_builder = request_builder.page_token(page_token)
                
            request = request_builder.request_body(request_body).build()

            response = self.client.bitable.v1.app_table_record.search(request)

            if response.success():
                if response.data and response.data.items:
                    all_records.extend(response.data.items)
                if response.data and response.data.has_more:
                    page_token = response.data.page_token
                else:
                    break # No more pages
            else:
                logger.error(f"Failed to search records, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}")
                # Save error response for debugging
                error_data_path = "./data/lark/search_error.json"
                os.makedirs(os.path.dirname(error_data_path), exist_ok=True)
                with open(error_data_path, 'w', encoding='utf-8') as f_err:
                    raw_resp = {}
                    if response.raw:
                        try:
                            raw_resp = json.loads(response.raw.content)
                        except json.JSONDecodeError:
                            raw_resp = {"content": response.raw.content.decode('utf-8', errors='replace')}
                    f_err.write(json.dumps({
                        "code": response.code,
                        "msg": response.msg,
                        "log_id": response.get_log_id(),
                        "raw_response": raw_resp
                    }, indent=2, ensure_ascii=False))
                return None # Return None on failure

        # Save all records data to file (optional, good for debugging)
        data_path = "./data/lark/latest_searched_records.json"
        try:
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            # We need to serialize each AppTableRecord object properly
            serializable_records = []
            for record in all_records:
                serializable_records.append({
                    "record_id": record.record_id,
                    "fields": record.fields,
                    # Add other attributes of AppTableRecord if needed
                })
            with open(data_path, 'w', encoding='utf-8') as f:
                # Instead of lark.JSON.marshal on response.data (which is now a list)
                json.dump({"items": serializable_records, "total": len(serializable_records)}, f, ensure_ascii=False, indent=2)
            logger.info(f"所有 {len(all_records)} 条记录已保存到: {data_path}")
        except Exception as e:
            logger.error(f"保存搜索到的记录数据失败: {str(e)}")
        
        # Mimic the structure of a single page response for compatibility,
        # but with all items.
        mock_response_data = lark.ޒ.model.BaseModel() # Generic base model for structure
        mock_response_data.items = all_records
        mock_response_data.has_more = False
        mock_response_data.page_token = None
        mock_response_data.total = len(all_records)
        
        return mock_response_data


    def list_table_fields(self, page_size=20):
        from lark_oapi.api.bitable.v1 import ListAppTableFieldRequest

        request_builder = ListAppTableFieldRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .page_size(page_size)

        if self.view_id:
            request_builder = request_builder.view_id(self.view_id)

        request = request_builder.build()

        response = self.client.bitable.v1.app_table_field.list(request)

        if response.success():
            logger.info(f"Fields: {lark.JSON.marshal(response.data, indent=4)}")
            return response.data
        else:
            logger.error(f"Failed to list fields, code: {response.code}, msg: {response.msg}")
            return None

    def update_record(self, record_id=None, fields_dict=None):
        request = UpdateAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .record_id(record_id) \
            .request_body(
                AppTableRecord.builder()
                .fields(fields_dict)
                .build()
            ) \
            .build()

        response = self.client.bitable.v1.app_table_record.update(request)

        if response.success():
            return response.data
        else:
            logger.error(f"Failed to update record, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}")
            return None

    def add_launch_to_bitable(self, launch: dict):
        """
        向多维表格新增一条火箭发射记录
        """
        status_map_zh = {
            "Success": "发射成功",
            "Failure": "发射失败",
            "Partial Success": "部分成功",
            "Scheduled": "计划中", 
            "Unknown": "状态未知",
            "TBD": "待定",
        }
        launch_status_zh = status_map_zh.get(launch.get("status", "Unknown"), "状态未知")

        # Ensure these field names match your Feishu Bitable columns
        fields = {
            "Rocket Model": launch.get("vehicle", ""),
            "发射任务名称": launch.get("mission", ""),
            "发射位": launch.get("pad_location", "Unknown"), # Use the new combined field
            "发射日期时间": launch.get("timestamp", 0) * 1000,
            "Source": launch.get("source_name", "Unknown"),
            "发射状态": launch_status_zh, # New field
            "发射任务描述": launch.get("mission_description", "N/A") # New field
        }
        
        if fields["发射日期时间"] == 0 and launch.get("status") != "Scheduled" and launch.get("status") != "TBD": # Avoid warning for legitimately TBD/Scheduled items with no firm time
            logger.warning(f"Launch '{launch.get('mission')}' from source '{launch.get('source_name')}' has a zero timestamp. It will be recorded with 0.")

        request = CreateAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .ignore_consistency_check(True) \
            .request_body(AppTableRecord.builder().fields(fields).build()) \
            .build()

        response = self.client.bitable.v1.app_table_record.create(request)
        if not response.success():
            logger.error(
                f"新增失败, Mission: {launch.get('mission', 'N/A')}, Code: {response.code}, Msg: {response.msg}, Log ID: {response.get_log_id()}"
            )
            try:
                error_details = json.loads(response.raw.content)
                logger.error(f"Error details: {json.dumps(error_details, indent=2, ensure_ascii=False)}")
            except: # nosec
                logger.error(f"Raw error response: {response.raw.content.decode(errors='ignore') if response.raw else 'N/A'}")
            return False
        
        return True