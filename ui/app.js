"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const paths = {
  folder:'<path d="M3 7h6l2 2h10v10H3z"/><path d="M3 7V5h6l2 2h8v2"/>',
  note:'<path d="M5 5h14v12H9l-4 3z"/><path d="M8 9h8m-8 3h5"/>',
  menu:'<path d="M3 6h18M3 12h18M3 18h18"/>', down:'<path d="m7 10 5 5 5-5"/>',
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
  discuss:'<path d="M3 5h13v10H7l-4 3z"/><path d="M18 9h3v11l-4-3h-6"/>',
  settings:'<path d="M4 7h5m4 0h7M4 17h10m4 0h2"/><circle cx="11" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>'
};
const icon = name => '<svg class="ic" aria-hidden="true" viewBox="0 0 24 24">'+paths[name]+'</svg>';
document.querySelectorAll("[data-icon]").forEach(el => el.innerHTML = icon(el.dataset.icon));
const labels = {codex:"Codex",gemini:"Gemini",claude:"Claude"};
const glyph = a => '<span aria-hidden="true" class="glyph '+a+'">'+({codex:"›_",gemini:"✦",claude:"∗"}[a])+'</span>';
const states = {stopped:"已停止",active:"讨论中",chat:"已回复",consensus:"已达成共识",disputed:"仍有分歧",incomplete:"未完成",implementing:"实施中",returned:"实施已返回",inspect:"实施中断",probe:"连接已验证"};
const ongoing = s => s === "active" || s === "implementing";
const num = n => Number(n || 0).toLocaleString();
const q = new URLSearchParams(location.search);
let project = q.get("project"), sid = q.get("session"), data, serial = 0, pending = false, poll, modalVersion = 0;
let detailOpen = false, noticeTimer;
const catalogs = new Map();
const draftKey = () => JSON.stringify([project,sid]);
const key = document.querySelector('meta[name="roundtable-key"]').content;
function saveDraft(){try{sessionStorage.setItem("roundtable:draft:"+draftKey(),$("topic").value);}catch{}}
function readDraft(){try{return sessionStorage.getItem("roundtable:draft:"+draftKey())||"";}catch{return "";}}
$("topic").oninput=saveDraft;
async function api(path, body) {
  const options = {headers:{"X-Roundtable":key}};
  if(body){options.method="POST";options.headers["Content-Type"]="application/json";options.body=JSON.stringify(body);}
  const resp = await fetch("/api/"+path, options);
  const result = await resp.json();
  if(!resp.ok) throw Error(result.error || "请求失败");
  return result;
}
function notify(msg){$("notice").textContent=msg;$("notice").hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$("notice").hidden=true,5500);}
function error(e){const el=$("formError");if($("modal").open){el.textContent=e.message;el.hidden=false;}else notify(e.message);}
function closeNav(){
  if(document.body.classList.contains("navopen"))$("menu").focus();
  document.body.classList.remove("navopen");
}
function address(){const u=new URL(location.href);u.search="";if(project)u.searchParams.set("project",project);if(sid)u.searchParams.set("session",sid);history.replaceState(null,"",u);}
async function refresh(){
  const stamp=++serial, query=new URLSearchParams();
  if(project)query.set("project",project);if(sid)query.set("session",sid);
  let next;
  try{
    next=await api("state?"+query);
  }catch(ex){
    if(stamp!==serial)return;
    const missingProject=project && ex.message.startsWith("找不到项目");
    if(missingProject || (sid && ex.message.includes("中找不到记录"))){
      if(missingProject)project="默认";
      sid=null;detailOpen=false;$("topic").value=readDraft();
      notify("项目或讨论已移除，已返回项目首页。");
      return refresh();
    }
    throw ex;
  }
  if(stamp!==serial)return;
  const changed=JSON.stringify(data)!==JSON.stringify(next);
  data=next;project=next.project;address();if(changed)render();
  clearTimeout(poll);
  poll=setTimeout(()=>refresh().catch(error),data.running.length || ongoing(data.selected?.state)?1200:10000);
}
async function navigate(p,id){
  saveDraft();
  clearTimeout(poll);serial++;project=p;sid=id;detailOpen=false;closeNav();
  $("topic").value=readDraft();
  $("stage").scrollTop=0;
  await refresh();
}
function inline(text){
  return esc(text).replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>");
}
function prose(text){
  return String(text || "").split(/^```[^\n]*$/m).map((block,i)=>i%2 ? "<pre>"+esc(block.trim())+"</pre>" :
    block.trim().split(/\n\s*\n/).filter(Boolean).map(part=>part.split("\n").map(line=>{
      const h=line.match(/^#{1,6}\s+(.+)$/);return h?"<h4>"+inline(h[1])+"</h4>":"<p>"+inline(line)+"</p>";
    }).join("")).join("")).join("");
}
function ballot(text){
  try{const b=JSON.parse(text);if(b.reason && ["accept","object"].includes(b.vote))return (b.vote==="accept"?"赞成 · ":"有异议 · ")+b.reason;}catch{}
  return text;
}
const levels={low:"低",medium:"中",high:"高",xhigh:"超高",max:"最高"};
function modelParts(id){
  const parts=id.split("-");
  const level=id.startsWith("gemini-") && Object.hasOwn(levels,parts.at(-1)) ? parts.pop() : "";
  const name=parts.map(w=>w==="gpt"?"GPT":w==="gemini"?"Gemini":w.charAt(0).toUpperCase()+w.slice(1)).join(" ").replace(/^GPT (\d)/,"GPT-$1");
  return {name,level};
}
function displayModel(id){
  if(!id)return "自动选择";
  const {name,level}=modelParts(id);
  return name+(level?" · "+levels[level]:"");
}
function seatCard(seat){
  const a=seat.agent, m=displayModel(seat.model);
  return '<button class="seat" type="button" data-agent="'+a+'" aria-label="选择 '+labels[a]+' 型号">'+glyph(a)+'<span class="text"><strong>'+labels[a]+'</strong><small title="'+esc(seat.model||m)+'">'+esc(m)+'</small></span>'+icon("down")+'</button>';
}
function render(){
  $("projectTitle").textContent=project;
  $("liveNav").hidden=!data.running.length;
  $("liveItems").innerHTML=data.running.map(r=>'<button class="navitem" data-live="'+esc(r.id)+'" data-owner="'+esc(r.project)+'"><span class="livepip"></span><span class="name">'+esc(r.topic)+'</span></button>').join("");
  $("projects").innerHTML=data.projects.map(p=>'<button class="navitem '+(p===project?'on':'')+'" data-project="'+esc(p)+'">'+icon("folder")+'<span class="name">'+esc(p)+'</span></button>').join("");
  $("history").innerHTML=data.sessions.map(s=>'<button class="navitem historyitem '+(sid===s.id?'on':'')+'" data-session="'+esc(s.id)+'" title="'+esc(s.topic)+'">'+icon("note")+'<span class="name">'+esc(s.topic)+'</span></button>').join("")||'<p class="emptyrail">还没有讨论</p>';
  $("seats").innerHTML=data.seats.map(seatCard).join("")+'<div class="seat off">'+glyph("claude")+'<span class="text"><strong>Claude</strong><small>尚未接入</small></span></div>';
  const d=document.querySelector(".indicator");
  d.className="indicator"+(data.seats.some(s=>s.status==="运行中")?" busy":data.seats.every(s=>s.status==="最近连通")?" good":"");
  const record=data.selected;
  $("stage").classList.toggle("reading",Boolean(record));
  $("conversation").hidden=!record;
  if(record) renderDiscussion(record);
  const busy=ongoing(record?.state);
  $("send").disabled=pending||busy;
  $("send").innerHTML=(busy?"进行中":record?"继续提问":$("mode").value==="both"?"开始讨论":"发送问题")+" "+icon("arrow");
  $("topic").placeholder=record?"补充条件，或继续追问…":"写下你的问题…";
}
function renderDiscussion(s){
  const calls=s.calls;
  const lastReply=stage=>calls.filter(c=>c.stage===stage && c.reply).slice(-1)[0]?.reply;
  const result=s.state==="returned"?lastReply("实施"):s.plan||lastReply("单聊");
  const resultLabel=s.state==="returned"?"实施报告":s.state==="consensus"?"共识方案":s.plan?"候选方案":"回复";
  const failures=calls.filter(c=>c.error);
  const lastStage=calls[calls.length-1]?.stage;
  const total=calls.reduce((v,c)=>v+(JSON.parse(c.usage||"{}").total||0),0);
  const stateStyle=["consensus","returned","chat","probe"].includes(s.state)?"done":["disputed","inspect","incomplete"].includes(s.state)?"warn":"";
  const busy=ongoing(s.state);
  const concise=s.topic.length>95 ? (s.topic.match(/^.{8,75}?[？。！？]/u)?.[0] || s.topic.slice(0,76)+"…") : s.topic;
  let html='<div class="topline"><span class="state '+stateStyle+'">'+esc(s.stop_requested&&busy?"正在停止":states[s.state]||s.state)+(busy&&lastStage?' · '+esc(lastStage):'')+'</span>';
  html+= busy ? '<button class="stop" id="stop" '+(s.stop_requested?'disabled':'')+'>'+ (s.stop_requested?'正在停止…':'■ 停止本轮')+'</button>' : '<button class="quiet remove-disc" id="removeSession" aria-label="移除这条讨论">移除讨论</button>';
  html+='</div><h1 class="topic-title">'+esc(concise)+'</h1>';
  if(concise!==s.topic)html+='<details class="original"><summary>原始议题</summary><p class="prose">'+esc(s.topic)+'</p></details>';
  if(busy || s.state==="stopped"){
    if(s.state==="stopped")html+='<p class="hint stopnote">'+(s.workspace?'实施已停止，请核对目录中已经写入的文件。':'本轮已停止。已收到的发言保存在下方，可以继续追问。')+'</p>';
    const live=calls.filter(c=>c.stage===lastStage);
    if(live.length)html+='<div class="lives">'+live.map(c=>{
      const waiting=!c.ended&&!c.reply, status=c.error?'已中断':c.ended?'已发言':c.reply?'发言中':'等待发言';
      const reply=c.stage.startsWith("表决")?ballot(c.reply):c.reply;
      return '<article class="livecard '+(waiting?'waiting':'')+'"><div class="callhead">'+glyph(c.agent)+'<b>'+labels[c.agent]+'</b><small>'+status+'</small></div>'+
        (reply?'<div class="prose">'+prose(reply)+'</div>':'<div class="waitline" aria-hidden="true"></div>')+'</article>';
    }).join("")+'</div>';
  }
  if(s.parent)html+='<button class="quiet" data-session="'+esc(s.parent)+'">← 上一轮讨论</button>';
  if(result)html+='<article class="result"><h3>'+resultLabel+'</h3><div class="prose">'+prose(result)+'</div></article>';
  if(s.state==="disputed")html+='<div class="result"><h3>待解决的分歧</h3>'+calls.filter(c=>c.stage===lastStage&&c.reply).map(c=>'<p class="prose">'+esc(labels[c.agent])+' · '+esc(ballot(c.reply))+'</p>').join("")+'</div>';
  if(s.state==="incomplete"&&!failures.length)html+='<p class="hint">本轮未收齐有效回复。可展开逐轮发言，或在「订阅额度」中检查连接。</p>';
  if(failures.length && s.state!=="stopped")html+='<p class="formerror">'+failures.map(c=>esc(labels[c.agent])+' · '+esc(c.error)).join("<br>")+'</p>';

  if(s.state==="consensus")html+='<div class="discussion-actions"><button id="implement" class="primary">交给 Codex 实施 '+icon("arrow")+'</button></div>';
  if(calls.length)html+='<details id="transcript"'+(detailOpen?' open':'')+'><summary>逐轮发言 · '+calls.length+' 次调用 · '+num(total)+' tokens</summary>'+calls.map(c=>{
    const t=JSON.parse(c.usage||"{}").total, reply=c.stage.startsWith("表决")?ballot(c.reply):c.reply;
    return '<article class="call"><div class="callhead"><b>'+esc(labels[c.agent])+'</b>'+esc(c.stage)+'<small>'+esc(c.model||"")+(t==null?"":" · "+num(t)+" tokens")+'</small></div><div class="prose">'+prose((c.error?c.error+'\n':'')+(reply||(c.ended?"无回复":"等待回复…")))+'</div></article>';
  }).join("")+'</details>';
  $("conversation").innerHTML=html;
  const tr=$("transcript");if(tr)tr.ontoggle=()=>{if(tr.isConnected)detailOpen=tr.open;};
}
function dialog(title,html){
  const d=$("modal");$("modalBody").onclick=null;$("modalTitle").textContent=title;$("modalBody").innerHTML=html;$("formError").hidden=true;
  if(!d.open)d.showModal();return ++modalVersion;
}
function dismiss(){modalVersion++;$("modal").close();}
$("closeModal").onclick=dismiss;
$("modal").addEventListener("close",()=>{modalVersion++;});
$("modal").addEventListener("click",e=>{if(e.target===$("modal")){const r=$("modal").getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dismiss();}});
async function pickModel(agent){
  const p=project, seat=data.seats.find(s=>s.agent===agent);
  const version=dialog("选择 "+labels[agent]+" 型号",'<input class="field" id="search" aria-label="搜索型号" placeholder="搜索型号…" autocomplete="off"><div class="options" id="choices"><p class="hint">正在读取本机 CLI 的型号清单…</p></div>');
  $("search").focus();
  try{
    const options=catalogs.get(agent)||(await api("catalog?agent="+agent)).models;
    catalogs.set(agent,options);
    if(version!==modalVersion)return;
    const draw=()=>{
      const query=$("search").value.trim().toLowerCase();
      const rows=new Map();
      for(const id of options){
        const {name,level}=modelParts(id);
        if(!(id+" "+name+" "+(levels[level]||"")).toLowerCase().includes(query))continue;
        if(!rows.has(name))rows.set(name,[]);
        rows.get(name).push({id,level});
      }
      let html=query?"":'<button class="option reset-model" data-value="default">使用默认型号</button>';
      for(const [name,variants] of rows){
        if(variants.every(v=>v.level)){
          variants.sort((a,b)=>Object.keys(levels).indexOf(a.level)-Object.keys(levels).indexOf(b.level));
          html+='<div class="variant"><strong>'+esc(name)+'</strong><div>'+variants.map(v=>
            '<button title="'+esc(v.id)+'" aria-label="'+esc(name+" · "+levels[v.level])+'" aria-pressed="'+(seat.model===v.id)+'" class="level" data-value="'+esc(v.id)+'">'+levels[v.level]+'</button>').join("")+'</div></div>';
        }else{
          html+=variants.map(v=>'<button class="option '+(v.id===seat.model?'active':'')+'" title="'+esc(v.id)+'" data-value="'+esc(v.id)+'">'+esc(displayModel(v.id))+(v.id===seat.model?'<b>✓</b>':'')+'</button>').join("");
        }
      }
      $("choices").innerHTML=html||'<p class="hint">没有匹配的型号</p>';
    };
    draw();$("search").oninput=draw;
    $("choices").onclick=async e=>{
      const b=e.target.closest("[data-value]");if(!b)return;
      try{await api("model",{project:p,agent,model:b.dataset.value});dismiss();await refresh();}catch(ex){error(ex);}
    };
  }catch(e){if(version===modalVersion){$("choices").textContent="";error(e);}}
}
function projectDialog(create){
  closeNav();
  dialog(create?"新建项目":"项目设置",'<form id="projectForm">'+(create?'<label for="pName">项目名称</label><input id="pName" class="field" placeholder="例如，文献检索" required maxlength="120">':'<p class="hint">'+esc(project)+'</p>')+
    '<label for="pPath">工作目录'+(create?'（可选）':'')+'</label><input id="pPath" class="field" value="'+esc(create?"":data.path)+'" placeholder="'+(create?'留空自动创建':'输入已有目录的路径')+'" '+(create?"":"required")+'><p class="hint">通过表决后，Codex 在此目录实施。</p><div class="dialogactions"><button class="primary">'+(create?'创建项目':'保存目录')+'</button></div></form>');
  if(!create && project!=="默认"){
    $("modalBody").insertAdjacentHTML("beforeend",'<div class="trashline"><button class="dangerlink" id="removeProject">移除项目…</button></div>');
    $("removeProject").onclick=()=>removeDialog("project",project,project);
  }
  (create?$("pName"):$("pPath")).focus();
  $("projectForm").onsubmit=async e=>{
    e.preventDefault();const b=e.submitter;b.disabled=true;
    try{
      const result=await api("project",{project,action:create?"add":"path",name:create?$("pName").value:"",path:$("pPath").value.trim()});
      dismiss();if(create)await navigate(result.project,null);else await refresh();
    }catch(ex){error(ex);}finally{b.disabled=false;}
  };
}
function removeDialog(kind,item,title){
  const p=project;
  dialog(kind==="project"?"移除这个项目？":"移除这条讨论？",'<p class="prose">'+esc(title)+'</p><p class="hint stopnote">'+
    (kind==="project"?'项目及其讨论将从侧栏收起。':'这条讨论及后续追问将从历史中收起。')+'工作目录和文件保留，可随时在回收站恢复。</p><div class="dialogactions"><button class="quiet" id="keep">取消</button><button class="destructive" id="confirmTrash">移入回收站</button></div>');
  $("keep").onclick=dismiss;
  $("confirmTrash").onclick=async e=>{const b=e.currentTarget;b.disabled=true;try{
    const r=await api("trash",{project:p,kind,item,action:"remove"});dismiss();await navigate(r.project,null);notify("已移入回收站");
  }catch(ex){error(ex);b.disabled=false;}};
}
async function trash(){
  closeNav();const p=project,version=dialog("回收站",'<p class="hint">正在读取…</p>');
  try{
    const r=await api("trash?project="+encodeURIComponent(p));if(version!==modalVersion)return;
    const group=(title,rows,kind)=>rows.length?'<h3 class="binhead">'+esc(title)+'</h3>'+rows.map(([id,name])=>'<div class="binrow"><span>'+esc(name)+'</span><button class="quiet restore" data-kind="'+kind+'" data-item="'+esc(id)+'">恢复</button></div>').join(""):"";
    $("modalBody").innerHTML=group("项目",r.projects.map(n=>[n,n]),"project")+group(p+" · 讨论",r.sessions.map(s=>[s.id,s.topic]),"session")||'<p class="hint">回收站是空的。</p>';
    $("modalBody").onclick=async e=>{const b=e.target.closest(".restore");if(!b)return;
      try{b.disabled=true;await api("trash",{project:p,kind:b.dataset.kind,item:b.dataset.item,action:"restore"});await refresh();await trash();}catch(ex){b.disabled=false;error(ex);}};
  }catch(ex){error(ex);}
}
function resetTime(value){
  if(value==null)return "重置时间未提供";
  const date=new Date(typeof value==="number"?value*1000:value);
  return Number.isNaN(+date)?"重置时间未提供":new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}).format(date)+" 重置";
}
const buckets={"gemini-5h":"Gemini · 5 小时","gemini-weekly":"Gemini · 每周","3p-5h":"Google 第三方模型池 · 5 小时","3p-weekly":"Google 第三方模型池 · 每周","gemini-argon-wtu-weekly":"Gemini Argon WTU · 每周"};
function health(force=false){
  const version=dialog("订阅额度",data.seats.map(s=>'<section class="qprovider"><div class="qtitle">'+glyph(s.agent)+'<b>'+labels[s.agent]+'</b><small>'+esc(s.status)+'</small></div><div id="quota-'+s.agent+'" class="qbody"><p class="hint">正在查询账号…</p></div></section>').join("")+
    '<p class="hint">Claude 尚未接入</p><div class="dialogactions"><button class="quiet" id="probe">实测连接</button><button class="primary" id="refreshQuota">刷新额度</button></div>');
  $("refreshQuota").onclick=()=>health(true);
  $("probe").onclick=async()=>{try{$("probe").disabled=true;const r=await api("start",{project,mode:"probe"});dismiss();await navigate(project,r.session);}catch(e){error(e);}};
  for(const seat of data.seats)(async()=>{
    try{
      const r=await api("quota?agent="+seat.agent+(force?"&refresh=1":""));
      if(version!==modalVersion)return;
      const order=w=>w.label.startsWith("gemini-5h")?0:w.label==="gemini-weekly"?1:2;
      const rows=r.windows.slice().sort((a,b)=>order(a)-order(b));
      $("quota-"+seat.agent).innerHTML=rows.map(w=>{
        const n=w.percent, title=buckets[w.label]||w.label;
        return '<div class="qrow"><div><span>'+esc(title)+'</span><b>'+(w.disabled?'已停用':n==null?'剩余 '+esc(w.amount):'剩余 '+esc(Number(n.toFixed(1)))+'%')+'</b></div>'+
          (n==null?'':'<meter min="0" max="100" value="'+esc(n)+'" aria-label="'+esc(title)+' 剩余额度"></meter>')+'<small>'+esc(resetTime(w.reset))+'</small></div>';
      }).join("")+'<small class="qstamp">'+(r.plan?esc(r.plan)+' · ':'')+(r.stale?'上次成功读取 ':'更新于 ')+esc(new Date(r.checked*1000).toLocaleTimeString())+'</small>'+(r.stale?'<p class="formerror">'+esc(r.error)+'</p>':'');
    }catch(ex){if(version===modalVersion)$("quota-"+seat.agent).innerHTML='<p class="hint">暂未取得账号额度。'+esc(ex.message)+'</p>';}
  })();
}
function runDialog(){
  const p=project, id=sid;
  dialog("交给 Codex 实施",'<form id="runForm"><label for="runPath">实施目录</label><input class="field" id="runPath" value="'+esc(data.path)+'" placeholder="输入已有项目目录" required><p class="hint">Codex 将按这份共识方案修改该目录中的文件。</p><div class="dialogactions"><button class="primary">开始实施</button></div></form>');
  $("runForm").onsubmit=async e=>{
    e.preventDefault();const dest=$("runPath").value.trim();if(!dest)return;
    dismiss();const request=api("implement",{project:p,session:id,path:dest});
    const timer=setTimeout(()=>{if(sid===id)refresh().catch(error);},400);
    try{await request;}catch(ex){error(ex);}finally{clearTimeout(timer);await refresh().catch(error);}
  };
}
document.addEventListener("click",async e=>{
  const b=e.target.closest("button");if(!b)return;
  try{
    if(b.dataset.live){await navigate(b.dataset.owner,b.dataset.live);return;}
    if(b.id==="stop"){b.disabled=true;await api("stop",{project,session:sid});await refresh();return;}
    if(b.id==="removeSession"){removeDialog("session",sid,data.selected.topic);return;}
    if(b.dataset.agent){await pickModel(b.dataset.agent);return;}
    if(b.dataset.project){const p=b.dataset.project;await api("project",{project,action:"use",name:p});await navigate(p,null);return;}
    if(b.dataset.session){await navigate(project,b.dataset.session);return;}
    if(b.id==="implement")runDialog();
  }catch(ex){error(ex);}
});
$("composer").onsubmit=async e=>{
  e.preventDefault();const topic=$("topic").value.trim();if(!topic||pending||!data||ongoing(data.selected?.state))return;
  const p=project, parent=sid;pending=true;render();
  try{
    const next=await api("start",{project:p,session:parent||"",topic,mode:$("mode").value});
    if(project===p&&sid===parent){$("topic").value="";await navigate(p,next.session);}
  }catch(ex){error(ex);}finally{pending=false;if(data)render();}
};
$("topic").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey)&&!e.isComposing){e.preventDefault();$("composer").requestSubmit();}});
$("new").onclick=async()=>{$("mode").value="both";await navigate(project,null);$("topic").value="";$("topic").focus();};
$("mode").onchange=()=>{if(data)render();};
$("settings").onclick=()=>projectDialog(false);$("add").onclick=()=>projectDialog(true);$("health").onclick=()=>health();$("trash").onclick=()=>trash();
$("menu").onclick=()=>{document.body.classList.add("navopen");$("closeNav").focus();};$("closeNav").onclick=closeNav;$("scrim").onclick=closeNav;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeNav();});
refresh().then(()=>{$("topic").value=readDraft();}).catch(error);
