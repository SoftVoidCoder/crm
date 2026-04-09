from pydantic import BaseModel

class AuthData(BaseModel): email: str; password: str = ""; name: str = ""
class RoleData(BaseModel): email: str; role: str; is_head: int = 0
class ClientData(BaseModel): name: str; inn: str = ""; contact: str = ""

# --- НОВЫЕ СХЕМЫ ДЛЯ НСИ И СКЛАДА ---
class NomenclatureData(BaseModel): name: str; article: str = ""; unit: str = "шт"; price: float = 0; stock: float = 0; currency: str = "RUB"
class StockMovement(BaseModel): qty: float; type: str # 'add' или 'remove'
class ContactData(BaseModel): client_id: int = 0; name: str; phone: str = ""; email: str = ""; position: str = ""

# Обновленные схемы проекта
class ProjectData(BaseModel): name: str; contract: str = "ТБД"; client: str = ""; manager: str = ""; budget: float = 0; costs: float = 0; team: list = []; checklist: list = []; allowed_roles: list = []; nomenclature: list = []
class ProjectUpdate(BaseModel): name: str; contract: str; client: str; manager: str; progress: float; status: str; checkedState: dict; comments: dict; deadlines: dict; budget: float = 0; costs: float = 0; chat: list = []; files: list = []; logs: list = []; team: list = []; checklist: list = []; escalations: dict = {}; archive_details: dict = {}; taskFiles: dict = {}; subtasks: dict = {}; time_logs: list = []; allowed_roles: list = []; nomenclature: list = []

class SignatureData(BaseModel): email: str; signature: str
class RemoveUserData(BaseModel): email: str
class VacationData(BaseModel): email: str; abs_start: str; abs_end: str; abs_type: str; abs_reason: str; deputy: str
class MeetingData(BaseModel): title: str; m_date: str; m_time: str; participants: list = []; agenda: list = []
class MeetingUpdate(BaseModel): title: str; m_date: str; m_time: str; participants: list = []; agenda: list = []; decisions: dict = {}; status: str
class GlobalChatData(BaseModel): name: str; creator: str; participants: list = []
class GlobalMessageData(BaseModel): user: str; role: str; text: str
class DocData(BaseModel): type: str; number: str; d_date: str; correspondent: str; subject: str; status: str; project_id: int = 0; parent_id: int = 0; priority: str = "normal"
class DocUpdate(BaseModel): type: str; number: str; d_date: str; correspondent: str; subject: str; status: str; project_id: int = 0; parent_id: int = 0; priority: str = "normal"
class TaskData(BaseModel): title: str; description: str; author: str; executor: str; deadline: str; recurrence: str = "none"; priority: str = "normal"; project_id: int = 0
class TaskUpdate(BaseModel): status: str; executor: str = None; history: list = None
class KnowledgeData(BaseModel): title: str; content: str; author: str; required_roles: list = []
class KnowledgeReadData(BaseModel): user: str
class ApprovalData(BaseModel): title: str; item_link: str; route: list; author: str
class ApprovalUpdate(BaseModel): current_step: int; status: str; history: list