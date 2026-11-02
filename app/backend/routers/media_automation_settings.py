from fastapi import APIRouter,Depends,Path,Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.media_automation_settings import Preview,Apply,TemplateSave
from routers.media_workspace import PrivateRoute
from services import media_automation_settings as service
router=APIRouter(prefix="/api/v1/media-automation-settings",tags=["media-automation-settings"],route_class=PrivateRoute)
@router.get("/templates")
async def templates(user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.templates(db,user)
@router.post("/templates")
async def save_template(body:TemplateSave,user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.save_template(db,user,**body.model_dump())
@router.get("/customers")
async def customers(search:str=Query("",max_length=100),after_id:int=Query(0,ge=0),user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.customers(db,user,search=search,after_id=after_id)
@router.get("/customers/{customer_id}")
async def get_settings(customer_id:int=Path(ge=1),month:str=Query(...),user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.get_settings(db,user,customer_id,month=month)
@router.post("/previews")
async def preview(body:Preview,user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.preview(db,user,body.model_dump())
@router.post("/previews/{preview_id}/apply")
async def apply(body:Apply,preview_id:str,user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.apply(db,user,preview_id,**body.model_dump())
@router.get("/requests/{request_id}")
async def result(request_id:str,user:UserResponse=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    return await service.request_result(db,user,request_id)
