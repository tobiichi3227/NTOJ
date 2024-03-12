from handlers.base import RequestHandler, reqenv, require_permission
from services.user import UserConst


class ManageDashHandler(RequestHandler):
    @reqenv
    @require_permission(UserConst.ACCTTYPE_KERNEL)
    async def get(self):
        await self.render('manage/dash', page='dash')
