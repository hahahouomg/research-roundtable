"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const paths = {
  folder:'<path d="M3 7h6l2 2h10v10H3z"/><path d="M3 7V5h6l2 2h8v2"/>',
  note:'<path d="M5 5h14v12H9l-4 3z"/><path d="M8 9h8m-8 3h5"/>',
  menu:'<path d="M3 6h18M3 12h18M3 18h18"/>', down:'<path d="m7 10 5 5 5-5"/>',
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
  discuss:'<path d="M3 5h13v10H7l-4 3z"/><path d="M18 9h3v11l-4-3h-6"/>',
  settings:'<path d="M4 7h5m4 0h7M4 17h10m4 0h2"/><circle cx="11" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>',
  home:'<path d="M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z"/>',
  up:'<path d="M12 19V5m-6 6 6-6 6 6"/>',
  list:'<path d="M9 7h11M9 12h11M9 17h11M4 7h1M4 12h1M4 17h1"/>',
  grid:'<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>',
  chevron:'<path d="m9 6 6 6-6 6"/>'
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
let lastSeatMarkup = "", detailOpen = false, noticeTimer, quotaSeq = 0, modalCancelHook = null, claudeSeq = 0, claudeErr = null;
const claudePending = new Map(), navMarkup = new WeakMap();
const motionAllowed = matchMedia("(prefers-reduced-motion: no-preference)");
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{
  const root=document.documentElement;
  root.classList.add("theme-switching");
  requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.remove("theme-switching")));
});
let shownDiscussion, lastRenderRecord, offline = false;
function updateMarkup(element, html){
  if(navMarkup.get(element)===html)return;
  element.innerHTML=html;
  navMarkup.set(element,html);
}
function enter(element, kind="content"){
  if(!motionAllowed.matches || document.hidden)return;
  const css=getComputedStyle(document.documentElement);
  element.getAnimations().filter(a=>a.id==="roundtable-entry").forEach(a=>a.cancel());
  const time=parseFloat(css.getPropertyValue("--motion-"+(kind==="overlay"?"overlay":"content")));
  const animation=element.animate([{opacity:0,transform:kind==="overlay"?"translateY(8px) scale(.99)":"translateY(4px)"},{opacity:1,transform:"none"}],{
    duration:time,easing:css.getPropertyValue("--motion-ease").trim()
  });
  animation.id="roundtable-entry";
}
function pollAgain(delay){
  clearTimeout(poll);
  if(!document.hidden)poll=setTimeout(()=>refresh().catch(error),delay);
}
function offlineState(value){
  if(offline===value)return;
  offline=value;
  $("offline").hidden=!value;
  if(value)enter($("offline"));
}
function patchChildren(target, source){
  let at=target.firstChild;
  const key=node=>node.nodeType===1 && (node.getAttribute("data-key") || node.id);
  const keyed=new Map([...target.children].filter(key).map(node=>[key(node),node]));
  for(const fresh of [...source.childNodes]){
    const id=key(fresh);
    const match=at && (id ? keyed.get(id) : at.nodeName===fresh.nodeName && !key(at) ? at : null);
    if(!match){
      target.insertBefore(fresh,at);
      if(fresh.nodeType===1 && fresh.matches(".permission,.lives,.result"))enter(fresh);
      continue;
    }
    if(match!==at)target.insertBefore(match,at);
    at=match.nextSibling;
    if(match.isEqualNode(fresh))continue;
    if(match.nodeType!==1){match.nodeValue=fresh.nodeValue;continue;}
    if(match.dataset.busy)continue;
    for(const attr of [...match.attributes]){
      if(!fresh.hasAttribute(attr.name) && !(attr.name==="open" && match.tagName==="DETAILS"))match.removeAttribute(attr.name);
    }
    for(const attr of fresh.attributes){
      if(match.getAttribute(attr.name)!==attr.value && !(attr.name==="open" && match.tagName==="DETAILS"))match.setAttribute(attr.name,attr.value);
    }
    patchChildren(match,fresh);
  }
  while(at){const next=at.nextSibling;at.remove();at=next;}
}
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
function notify(msg){const notice=$("notice");notice.textContent=msg;notice.hidden=false;notice.animate([{opacity:.2},{opacity:1}],motionAllowed.matches?150:0);clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$("notice").hidden=true,5500);}
function error(e){const el=$("formError");if($("modal").open){const hidden=el.hidden;el.textContent=e.message;el.hidden=false;if(hidden)enter(el);}else notify(e.message);}
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
    if(ex instanceof TypeError){offlineState(true);pollAgain(2500);return;}
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
  offlineState(false);
  const changed=JSON.stringify(data)!==JSON.stringify(next);
  data=next;project=next.project;address();if(changed)render();
  pollAgain(data.running.length || data.selected?.calls.some(c=>!c.ended)?1200:5000);
}
async function navigate(p,id){
  saveDraft();
  if(p!==project || id!==sid)$("moderator").value="";
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
const levels={low:"低",medium:"中",high:"高",xhigh:"超高",max:"最高",ultra:"极致"};
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
  const a=seat.agent, m=displayModel(seat.model)+(seat.effort?" · "+(levels[seat.effort]||seat.effort):"");
  return '<button class="seat" type="button" data-key="seat-'+a+'" data-agent="'+a+'" aria-label="选择 '+labels[a]+' 型号">'+glyph(a)+'<span class="text"><strong>'+labels[a]+'</strong><small title="'+esc(seat.model||m)+'">'+esc(m)+'</small></span>'+icon("down")+'</button>';
}
function claudeCard(seat){
  const state=claudePending.get(project);
  const enabled=Boolean(seat), checked=state?state.from:enabled;
  const showModel=checked && Boolean(seat);
  const m=showModel ? displayModel(seat.model)+(seat.effort?" · "+(levels[seat.effort]||seat.effort):"") : "";
  const left=showModel && !state
    ? '<button class="seat-trigger" type="button" data-agent="claude" aria-label="选择 Claude 型号和思考强度">'+glyph("claude")+'<span class="text"><strong>Claude</strong><small title="'+esc(seat.model||m)+'">'+esc(m)+'</small></span>'+icon("down")+'</button>'
    : '<div class="seat-trigger '+(showModel?'':'is-off')+'">'+glyph("claude")+'<span class="text"><strong>Claude</strong><small title="'+esc(showModel?seat.model||"":"")+'">'+esc(showModel?m:"未参与当前项目")+'</small></span></div>';
  const label=state ? (state.target==="on"?"校验中…":"关闭中…") : checked ? "已开启" : "已关闭";
  return '<div class="seat seat-claude '+(checked?"on":"off")+'" data-key="seat-claude" data-seat="claude">'+left+
    '<button class="seat-switch" type="button" id="claudeToggle" role="switch" aria-checked="'+(checked?"true":"false")+'"'+(state?' disabled aria-busy="true"':'')+
    ' aria-label="'+esc("项目「"+project+"」的 Claude 席位开关")+'" data-claude-toggle>'+
    '<span class="switch-track" aria-hidden="true"><span class="switch-thumb"></span></span>'+
    '<span class="switch-label">'+label+'</span></button></div>';
}
function render(){
  $("projectTitle").textContent=project;
  $("liveNav").hidden=!data.running.length;
  updateMarkup($("liveItems"),data.running.map(r=>'<button class="navitem" data-live="'+esc(r.id)+'" data-owner="'+esc(r.project)+'"><span class="livepip"></span><span class="name">'+esc(r.topic)+'</span>'+(r.awaiting?'<small>待确认</small>':'')+'</button>').join(""));
  updateMarkup($("projects"),data.projects.map(p=>'<button class="navitem '+(p===project?'on':'')+'" data-project="'+esc(p)+'">'+icon("folder")+'<span class="name">'+esc(p)+'</span></button>').join(""));
  updateMarkup($("history"),data.sessions.map(s=>'<button class="navitem historyitem '+(sid===s.id?'on':'')+'" data-session="'+esc(s.id)+'" title="'+esc(s.topic)+'">'+icon("note")+'<span class="name">'+esc(s.topic)+'</span></button>').join("")||'<p class="emptyrail">还没有讨论</p>');
  const claudeSeat=data.seats.find(s=>s.agent==="claude"), claudeEnabled=Boolean(claudeSeat);
  const seatMarkup=data.seats.filter(s=>s.agent!=="claude").map(seatCard).join("")+claudeCard(claudeSeat);
  if(seatMarkup!==lastSeatMarkup){
    const template=document.createElement("template");template.innerHTML=seatMarkup;
    patchChildren($("seats"),template.content);lastSeatMarkup=seatMarkup;
  }
  const showClaudeErr=claudeErr && claudeErr.project===project;
  $("claudeError").hidden=!showClaudeErr;
  $("claudeError").textContent=showClaudeErr?claudeErr.message:"";
  const modeEl=$("mode"), claudeMode=modeEl.querySelector('[value="claude"]');
  if(claudeEnabled){if(!claudeMode)modeEl.add(new Option("只问 Claude","claude"));}
  else{if(modeEl.value==="claude")modeEl.value="both";if(claudeMode)claudeMode.remove();}
  const moderator=$("moderator"), claudeModerator=moderator.querySelector('[value="claude"]');
  if(claudeEnabled && !claudeModerator)moderator.add(new Option("Claude","claude"));
  if(!claudeEnabled && claudeModerator){if(moderator.value==="claude")moderator.value="";claudeModerator.remove();}
  $("moderatorField").hidden=modeEl.value!=="both";
  const record=data.selected;
  $("stage").classList.toggle("reading",Boolean(record));
  $("conversation").hidden=!record;
  if(record && record!==lastRenderRecord)renderDiscussion(record);
  if(shownDiscussion!==record?.id){
    enter(record?$("conversation"):$("intro"));
    shownDiscussion=record?.id;
  }
  lastRenderRecord=record;
  const busy=ongoing(record?.state);
  $("send").disabled=pending||busy;
  $("send").innerHTML=(pending?"正在发送…":busy?"进行中":record?"继续提问":$("mode").value==="both"?"开始讨论":"发送问题")+" "+icon("arrow");
  $("topic").placeholder=record?"补充条件，或继续追问…":"写下你的问题…";
}
function finalDraft(s){
  return s.calls.find(c=>c.stage==="最终方案撰写" && c.agent==="gemini" && c.ended && !c.error)?.reply;
}
function permissionCard(req, expanded){
  const d=req.details, input=d.rawInput||d.args||{};
  const command=input.CommandLine||input.command;
  const summary=input.toolSummary||d.title||d.kind||"工具请求";
  const detail=Object.fromEntries(Object.entries(d).filter(([k])=>k!=="cwd"));
  return '<section class="permission" data-key="permission-'+req.id+'" aria-label="Gemini 工具授权"><h3>Gemini 正在等你确认</h3>'+
    '<p>'+esc(req.stage)+' · '+esc(summary)+'</p><p class="hint">工作目录 · '+esc(d.cwd)+'</p>'+
    (typeof command==="string"?'<pre>'+esc(command)+'</pre>':'')+
    '<details data-request-detail="'+req.id+'" '+(expanded||!command?'open':'')+'><summary>完整工具参数</summary><pre>'+esc(JSON.stringify(detail,null,2))+'</pre></details>'+
    '<div class="dialogactions"><button class="quiet" data-permission="'+req.id+'" data-choice="deny">拒绝并停止本席</button>'+
    (req.can_allow?'<button class="primary" data-permission="'+req.id+'" data-choice="allow">仅允许这一次</button>':'')+'</div></section>';
}
function renderDiscussion(s){
  const calls=s.calls;
  const lastReply=stage=>calls.filter(c=>c.stage===stage && c.reply).slice(-1)[0]?.reply;
  const reports=calls.filter(c=>["实施","集成复核"].includes(c.stage) && c.reply).map(c=>{
    let report=c.reply;
    try{report=JSON.parse(c.reply).report||report;}catch{}
    return labels[c.agent]+" · "+c.stage+" · "+report;
  });
  const draft=finalDraft(s);
  const result=reports.length?reports.join("\n\n"):draft||s.plan||lastReply("单聊");
  const resultLabel=reports.length?"实施报告":draft?"最终方案 · Gemini 执笔":s.state==="consensus"?"共识方案":s.plan?"候选方案":"回复";
  const failures=calls.filter((c,i)=>c.error && !calls.slice(i+1).some(n=>n.stage===c.stage && n.agent===c.agent && n.ended && !n.error));
  const lastStage=calls[calls.length-1]?.stage;
  const totals=calls.map(c=>JSON.parse(c.usage||"{}").total).filter(Number.isFinite);
  const used=totals.length?num(totals.reduce((sum,n)=>sum+n,0))+" tokens":"用量待回报";
  const stateStyle=["consensus","returned","chat","probe"].includes(s.state)?"done":["disputed","inspect","incomplete"].includes(s.state)?"warn":"";
  const busy=ongoing(s.state);
  const concise=s.topic.length>95 ? (s.topic.match(/^.{8,75}?[？。！？]/u)?.[0] || s.topic.slice(0,76)+"…") : s.topic;
  let html='<div class="topline"><span class="state '+stateStyle+'" aria-live="polite">'+esc(s.stop_requested&&busy?"正在停止":states[s.state]||s.state)+(busy&&lastStage?' · '+esc(lastStage):'')+'</span>';
  if(!busy)html+='<button class="quiet jump-reply" id="jumpReply">去追问</button>';
  if(s.moderator)html+='<span class="hint moderator-label">主持 · '+esc(labels[s.moderator])+'</span>';
  html+= busy ? '<button class="stop" id="stop" '+(s.stop_requested?'disabled':'')+'>'+ (s.stop_requested?'正在停止…':s.state==="implementing"?'停止实施':'停止本轮')+'</button>' : "";
  html+='</div><h1 class="topic-title">'+esc(concise)+'</h1>';
  for(const request of s.permissions||[]){
    const expanded=document.querySelector('[data-request-detail="'+request.id+'"]')?.open;
    html+=permissionCard(request,expanded);
  }
  if(concise!==s.topic)html+='<details class="original" data-key="source-topic"><summary>原始议题</summary><p class="prose">'+esc(s.topic)+'</p></details>';
  if(busy || s.state==="stopped"){
    if(s.state==="stopped")html+='<p class="hint stopnote">'+(s.workspace?'实施已停止，请核对目录中已经写入的文件。':'本轮已停止。已收到的发言保存在下方，可以继续追问。')+'</p>';
    const live=calls.filter(c=>c.stage===lastStage);
    if(live.length)html+='<div class="lives">'+live.map(c=>{
      const approval=!c.ended && c.agent==="gemini" && s.permissions?.some(r=>r.stage===c.stage);
      const waiting=!c.ended&&!c.reply, status=approval?'待你确认':c.error?'已中断':c.ended?'已发言':c.reply?'发言中':'等待发言';
      const reply=c.stage.startsWith("表决")?ballot(c.reply):c.reply;
      return '<article data-key="live-'+c.id+'" class="livecard '+(waiting?'waiting':'')+'"><div class="callhead">'+glyph(c.agent)+'<b>'+labels[c.agent]+'</b><small>'+status+'</small></div>'+
        (reply?'<div class="prose">'+prose(reply)+'</div>':'<div class="waitline" aria-hidden="true"></div>')+'</article>';
    }).join("")+'</div>';
  }
  if(s.workspace)html+='<p class="hint">实施目录 · '+esc(s.workspace)+'</p>';
  if(s.plan && !busy)html+='<button class="quiet" id="exportPlan">下载'+(s.state==="disputed"?"候选方案":"方案")+'</button>';
  if(draft && !busy)html+='<button class="quiet" id="exportPDF">'+(s.has_pdf?'下载图文 PDF':'请 Gemini 排版 PDF')+'</button>';
  if(!busy)html+='<button class="quiet" id="discussionFolder">'+icon("folder")+' 记录文件夹</button>';
  if(calls.length && !busy)html+='<button class="quiet" id="exportRecord">下载讨论记录</button>';
  if(s.parent)html+='<button class="quiet" data-session="'+esc(s.parent)+'">← 上一轮讨论</button>';
  if(result)html+='<article class="result"><h3>'+resultLabel+'</h3><div class="prose">'+prose(result)+'</div></article>';
  if(draft)html+='<details data-key="approved-plan"><summary>全体表决通过的原稿及分工</summary><div class="prose">'+prose(s.plan)+'</div></details>';
  if(s.state==="disputed")html+='<div class="result"><h3>待解决的分歧</h3>'+calls.filter(c=>c.stage===lastStage&&c.reply).map(c=>'<p class="prose">'+esc(labels[c.agent])+' · '+esc(ballot(c.reply))+'</p>').join("")+'<button id="continueDispute" class="quiet">根据异议继续讨论</button></div>';
  if(s.notice)html+='<p class="hint">'+esc(s.notice)+'</p>';
  if(s.failure && (s.state!=="incomplete" || !failures.length))html+='<p class="formerror">'+esc(s.failure)+'</p>';
  if((s.state==="incomplete" && (s.can_resume || calls.some(c=>c.stage==="独立提案"))) || (s.state==="consensus" && !draft && calls.some(c=>c.stage==="最终方案撰写" && c.error)))html+='<button id="resumeDiscussion" class="quiet">从中断阶段续跑</button>';
  if(s.state==="incomplete"&&!s.failure&&!failures.length)html+='<p class="hint">本轮未收齐有效回复。可展开逐轮发言，或在「订阅额度」中查看账号额度。</p>';
  if(failures.some(c=>c.error.includes("额度或频率受限")))html+='<button class="quiet" id="failureQuota">查看订阅额度</button>';
  if(failures.length && s.state!=="stopped")html+='<p class="formerror">'+failures.map(c=>esc(labels[c.agent])+' · '+esc(c.error)).join("<br>")+'</p>';

  if(s.state==="consensus")html+='<div class="discussion-actions"><button id="implement" class="primary">按分工实施 '+icon("arrow")+'</button></div>';
  if(calls.length)html+='<details id="transcript"'+(detailOpen?' open':'')+'><summary>逐轮发言 · '+calls.length+' 次调用 · '+esc(used)+'</summary>'+(detailOpen?calls.map(c=>{
    const t=JSON.parse(c.usage||"{}").total, reply=c.stage.startsWith("表决")?ballot(c.reply):c.reply;
    return '<article data-key="call-'+c.id+'" class="call"><div class="callhead"><b>'+esc(labels[c.agent])+'</b>'+esc(c.stage)+'<small>'+esc([c.model,c.effort].filter(Boolean).join(" · "))+(t==null?"":" · "+num(t)+" tokens")+'</small></div><div class="prose">'+prose((c.error?c.error+'\n':'')+(reply||(c.ended?"无回复":"等待回复…")))+'</div></article>';
  }).join(""):"")+'</details>';
  const target=$("conversation"), template=document.createElement("template");
  template.innerHTML=html;
  if(shownDiscussion!==s.id)target.replaceChildren(template.content);
  else patchChildren(target,template.content);
  const tr=$("transcript");if(tr)tr.ontoggle=()=>{
    if(tr.isConnected && detailOpen!==tr.open){detailOpen=tr.open;renderDiscussion(s);}
  };
}
function dialog(title,html){
  const d=$("modal");modalCancelHook=null;d.classList.remove("wide");
  $("modalBody").onclick=null;$("modalTitle").textContent=title;$("modalBody").innerHTML=html;$("formError").hidden=true;
  if(!d.open)d.showModal();
  enter(d,"overlay");
  return ++modalVersion;
}
function dismiss(){modalCancelHook=null;$("modal").classList.remove("wide");modalVersion++;$("modal").close();}
$("closeModal").onclick=dismiss;
$("modal").addEventListener("cancel",e=>{if(modalCancelHook){e.preventDefault();modalCancelHook();}});
$("modal").addEventListener("close",()=>{if($("modal").open)return;modalCancelHook=null;$("modal").classList.remove("wide");modalVersion++;});
$("modal").addEventListener("click",e=>{if(e.target===$("modal")){const r=$("modal").getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dismiss();}});
async function pickModel(agent){
  const p=project, seat=data.seats.find(s=>s.agent===agent);
  if(!seat)return;
  const version=dialog("选择 "+labels[agent]+(agent!=="gemini"?" 型号和思考强度":" 型号"),'<input class="field" id="search" aria-label="搜索型号" placeholder="搜索型号…" autocomplete="off"><div class="options" id="choices"><p class="hint">正在读取本机 CLI 的型号清单…</p></div>');
  $("search").focus();
  try{
    const catalog=await api("catalog?agent="+agent);
    const options=catalog.models;
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
        if(agent!=="gemini"){
          for(const {id} of variants){
            const effortButtons=["default",...(catalog.efforts[id]||[])].map(v=>
              '<button class="level" data-value="'+esc(id)+'" data-effort="'+esc(v)+'" aria-label="'+esc(name+" 思考强度 "+(levels[v]||v))+'" aria-pressed="'+(seat.model===id && (seat.effort||"default")===v)+'">'+esc(v==="default"?"默认":levels[v]||v)+'</button>').join("");
            html+='<div class="variant"><strong>'+esc(name)+'</strong><div>'+effortButtons+'</div></div>';
          }
        }else if(variants.every(v=>v.level)){
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
      try{await api("model",{project:p,agent,model:b.dataset.value,effort:b.dataset.effort||""});dismiss();await refresh();}catch(ex){error(ex);}
    };
  }catch(e){if(version===modalVersion){$("choices").textContent="";error(e);}}
}
function projectDialog(create){
  closeNav();
  dialog(create?"新建项目":"项目设置",'<form id="projectForm">'+(create?'<label for="pName">项目名称</label><input id="pName" class="field" placeholder="例如，文献检索" required maxlength="120">':'<p class="hint">'+esc(project)+'</p>')+
    '<label for="pPath">工作目录'+(create?'（可选）':'')+'</label><input id="pPath" class="field" value="'+esc(create?"":data.path)+'" placeholder="'+(create?'留空自动创建':'输入已有目录的路径')+'" '+(create?"":"required")+'><p class="hint">讨论时各席使用此目录的实验副本。确认实施后按分工写入原目录。</p><div class="dialogactions"><button class="primary">'+(create?'创建项目':'保存目录')+'</button></div></form>');
  directoryPicker("pPath");
  if(!create){
    $("modalBody").insertAdjacentHTML("beforeend",
      '<section class="project-storage"><h3>讨论数据</h3><button type="button" class="quiet" id="projectFolder">'+icon("folder")+' 项目记录文件夹</button></section>'+
      '<details class="advanced"><summary>工具与运行</summary><form id="preferences">'+
      '<label for="geminiMode">Gemini 工具权限</label><select class="field" id="geminiMode"><option value="auto">优先 Auto</option><option value="cli">跟随 CLI</option><option value="review">每次确认</option></select>'+
      '<p class="hint">Auto 由 agy 提供，仍可能请你在网页确认。CLI 的禁止规则优先。</p>'+
      '<label for="timeout">单次调用超时（分钟）</label><input id="timeout" class="field" type="number" min="1" max="120" placeholder="默认 5 分钟，实施 20 分钟" value="'+esc(data.call_minutes??"")+'">'+
      '<p class="hint">等待工具确认的时间另计。</p><div class="dialogactions"><button class="primary">保存运行设置</button></div></form>'+
      (data.isolated_lab_available?'<label><input type="checkbox" id="autoLab" '+(data.auto_lab?'checked':'')+'> Gemini 自动运行离线实验</label>':'')+
      '<button class="quiet" type="button" id="claudeConfig">Claude 出口设置</button></details>');
    $("geminiMode").value=data.gemini_mode;
    $("preferences").onsubmit=async e=>{
      e.preventDefault();
      const b=e.submitter;b.disabled=true;
      try{
        await api("preferences",{project,gemini_mode:$("geminiMode").value,minutes:$("timeout").value});
        await refresh();notify("已保存运行设置");
      }catch(ex){error(ex);}finally{b.disabled=false;}
    };
    if($("autoLab"))$("autoLab").onchange=async e=>{
      const btn=e.target;btn.disabled=true;
      try{await api("auto-lab",{project,enabled:btn.checked?"on":"off"});await refresh();notify("已保存实验权限");}
      catch(ex){btn.checked=!btn.checked;error(ex);}finally{btn.disabled=false;}
    };
    $("claudeConfig").onclick=()=>claudeConfig(false);
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
function pathCrumbs(path, sep){
  if(path===":drives")return [{label:"磁盘",path}];
  const parts=path.split(sep).filter(Boolean), win=sep==="\\";
  const base=win?(path.startsWith(sep+sep)?sep+sep+parts.splice(0,2).join(sep)+sep:parts.shift()+sep):"/";
  const out=[{label:base,path:base}];
  if(win)out.unshift({label:"磁盘",path:":drives"});
  let cur=base;
  for(const seg of parts){cur=cur+(cur.endsWith(sep)?"":sep)+seg;out.push({label:seg,path:cur});}
  return out;
}
function directoryPicker(inputId){
  const input=$(inputId), openModalVersion=modalVersion;
  input.insertAdjacentHTML("afterend",
    '<div class="path-actions">'+
      '<button type="button" class="quiet" data-dir-native>'+icon("folder")+'<span>选择目录…</span></button>'+
      '<button type="button" class="quiet" data-dir-web aria-expanded="false">在网页中浏览</button>'+
    '</div>'+
    '<section class="fb" hidden aria-label="网页目录浏览器"></section>');
  const actions=input.nextElementSibling;
  const nativeBtn=actions.querySelector("[data-dir-native]");
  const webBtn=actions.querySelector("[data-dir-web]");
  const panel=actions.nextElementSibling;
  const submit=input.form.querySelector(".dialogactions .primary");
  let pickingNative=false, browserOpen=false, opSeq=0, browseSeq=0, loadingPath=null;
  let viewMode="list", currentListing=null, fallbackNote="";

  function closeBrowser(restoreFocus){
    if(!browserOpen)return;
    browserOpen=false;
    submit.disabled=false;
    browseSeq++;
    loadingPath=null;
    panel.hidden=true;
    webBtn.setAttribute("aria-expanded","false");
    modalCancelHook=null;
    if(openModalVersion===modalVersion)$("modal").classList.remove("wide");
    if(restoreFocus && webBtn.isConnected)webBtn.focus();
  }

  function renderBrowser(opts={}){
    const listing=currentListing;
    const crumbs=listing?pathCrumbs(listing.path,listing.separator):[];
    const atRoot=!listing || !listing.parent || listing.path===listing.parent;
    const atHome=Boolean(listing?.home && listing.path===listing.home);
    const folders=listing?.drives||listing?.folders||[];
    let bodyHtml="";
    if(opts.error){
      bodyHtml='<div class="fb-error" role="alert"><p>'+esc(opts.error)+'</p><div class="fb-error-actions">'+
        (listing?'<button type="button" class="quiet" data-fb="back-listing">返回当前目录</button>':'')+
        '<button type="button" class="quiet" data-fb="home-fallback">前往主目录</button></div></div>';
    }else if(!listing){
      bodyHtml='<div class="fb-empty" aria-live="polite"><p>正在读取目录…</p></div>';
    }else if(!folders.length){
      bodyHtml='<div class="fb-empty">'+icon("folder")+'<p>此目录下没有子文件夹</p><small>可直接点击「选择此目录」，或返回上一级</small></div>';
    }else{
      bodyHtml='<div class="fb-items '+viewMode+'" aria-label="子文件夹列表">'+folders.map(name=>
        '<button type="button" class="fb-item" data-folder="'+esc(name)+'" title="'+esc(name)+'">'+
        '<span class="fb-folder-ic" aria-hidden="true">'+icon("folder")+'</span>'+
        '<span class="fb-name">'+esc(name)+'</span>'+
        '<span class="fb-go" aria-hidden="true">'+icon("chevron")+'</span></button>').join("")+'</div>';
    }
    const crumbsHtml=crumbs.length ? crumbs.map((c,i)=>{
      const last=i===crumbs.length-1;
      return (i?'<span class="fb-sep" aria-hidden="true">/</span>':'')+
        '<button type="button" class="fb-crumb" data-fb-path="'+esc(c.path)+'"'+(last?' aria-current="location"':'')+' title="'+esc(c.path)+'">'+esc(c.label)+'</button>';
    }).join("") : '<span class="hint">位置</span>';
    panel.innerHTML=
      '<div class="fb-toolbar">'+
        '<button type="button" class="fb-navbtn" data-fb="home"'+(atHome?' aria-current="location"':'')+' title="前往主目录">'+icon("home")+'主目录</button>'+
        '<button type="button" class="fb-navbtn" data-fb="parent"'+(atRoot?' disabled':'')+' title="返回上一级 (Backspace)">'+icon("up")+'上一级</button>'+
        '<div class="fb-views" role="group" aria-label="视图方式">'+
          '<button type="button" class="fb-viewbtn" data-fb-view="list" aria-label="列表视图" title="列表视图" aria-pressed="'+(viewMode==="list")+'">'+icon("list")+'</button>'+
          '<button type="button" class="fb-viewbtn" data-fb-view="grid" aria-label="网格视图" title="网格视图" aria-pressed="'+(viewMode==="grid")+'">'+icon("grid")+'</button>'+
        '</div>'+
      '</div>'+
      (fallbackNote?'<p class="fb-note">'+esc(fallbackNote)+'</p>':'')+
      '<nav class="fb-crumbs" aria-label="目录位置">'+crumbsHtml+'</nav>'+
      '<div class="fb-body'+(opts.loading?' loading':'')+'"'+(opts.loading?' aria-busy="true"':'')+'>'+bodyHtml+'</div>'+
      '<div class="fb-footer">'+
        '<div class="fb-selected"><span class="fb-sel-label">当前选择</span><code class="fb-sel-path" title="'+esc(listing?.path||"")+'">'+esc(listing?.path||"尚未读取")+'</code></div>'+
        '<div class="fb-foot-actions">'+
          '<button type="button" class="quiet" data-fb="cancel">取消</button>'+
          '<button type="button" class="primary" data-fb="confirm"'+(listing?.path && !listing.drives && loadingPath===null && !opts.error?'':' disabled')+'>选择此目录</button>'+
        '</div>'+
      '</div>';
    const crumbsEl=panel.querySelector(".fb-crumbs");
    if(crumbsEl)crumbsEl.scrollLeft=crumbsEl.scrollWidth;
  }

  async function loadDir(targetPath, focusBody=false){
    if(loadingPath!==null && loadingPath===targetPath)return;
    const reqId=++browseSeq;
    loadingPath=targetPath;
    if(!currentListing)renderBrowser({loading:true});
    else{
      const body=panel.querySelector(".fb-body");
      panel.querySelector('[data-fb="confirm"]').disabled=true;
      if(body){body.classList.add("loading");body.setAttribute("aria-busy","true");}
    }
    try{
      const res=await api("directories?"+new URLSearchParams({path:targetPath}));
      if(reqId===browseSeq)loadingPath=null;
      if(reqId!==browseSeq || !browserOpen || openModalVersion!==modalVersion || !panel.isConnected)return;
      currentListing={
        path:res.path||"",
        parent:res.parent||"",
        home:res.home||"",
        folders:res.folders||[], drives:res.drives, separator:res.separator||"/"
      };
      renderBrowser();
      const body=panel.querySelector(".fb-body");
      if(body){body.scrollTop=0;enter(body);}
      if(focusBody){
        const nextFocus=panel.querySelector(".fb-item") || panel.querySelector('[data-fb="confirm"]:not(:disabled)') || panel.querySelector('[data-fb="parent"]:not(:disabled)');
        nextFocus?.focus();
      }
    }catch(ex){
      if(reqId===browseSeq)loadingPath=null;
      if(reqId!==browseSeq || !browserOpen || openModalVersion!==modalVersion || !panel.isConnected)return;
      renderBrowser({error:ex?.message||"无法读取该目录"});
      if(focusBody)panel.querySelector('[data-fb="home-fallback"]')?.focus();
    }
  }

  function openBrowser(startPath, note=""){
    opSeq++;
    fallbackNote=note;
    browserOpen=true;
    submit.disabled=true;
    currentListing=null;
    loadingPath=null;
    panel.hidden=false;
    webBtn.setAttribute("aria-expanded","true");
    $("modal").classList.add("wide");
    modalCancelHook=()=>closeBrowser(true);
    loadDir(startPath, true);
    enter(panel);
    panel.scrollIntoView({block:"nearest"});
  }

  panel.onclick=e=>{
    const btn=e.target.closest("button");
    if(!btn || btn.disabled)return;
    if(btn.dataset.fb==="home" || btn.dataset.fb==="home-fallback"){loadDir(currentListing?.home||"",true);}
    else if(btn.dataset.fb==="back-listing"){renderBrowser();}
    else if(btn.dataset.fb==="parent"){if(currentListing?.parent && currentListing.parent!==currentListing.path)loadDir(currentListing.parent,true);}
    else if(btn.dataset.fb==="confirm"){
      if(!currentListing?.path || loadingPath!==null)return;
      input.value=currentListing.path;
      closeBrowser(false);
      input.focus();
    }else if(btn.dataset.fb==="cancel"){
      closeBrowser(true);
    }else if(btn.dataset.fbView){
      viewMode=btn.dataset.fbView;
      renderBrowser();
      panel.querySelector('[data-fb-view="'+viewMode+'"]')?.focus();
    }else if(btn.dataset.fbPath!=null){
      loadDir(btn.dataset.fbPath,true);
    }else if(btn.dataset.folder!=null && currentListing){
      loadDir(currentListing.drives?btn.dataset.folder:currentListing.path+(currentListing.path.endsWith(currentListing.separator)?"":currentListing.separator)+btn.dataset.folder,true);
    }
  };

  panel.onkeydown=e=>{
    if(e.key==="Escape"){
      e.preventDefault();e.stopPropagation();closeBrowser(true);return;
    }
    if((e.key==="Backspace" && !e.target.closest("input,textarea")) || (e.altKey && e.key==="ArrowUp")){
      if(currentListing?.parent && currentListing.parent!==currentListing.path){
        e.preventDefault();loadDir(currentListing.parent,true);
      }
      return;
    }
    if(e.key==="Enter" && (e.metaKey || e.ctrlKey)){
      if(currentListing?.path && !panel.querySelector('[data-fb="confirm"]').disabled){
        e.preventDefault();input.value=currentListing.path;closeBrowser(false);input.focus();
      }
      return;
    }
    const item=e.target.closest(".fb-item");
    if(!item)return;
    const items=[...panel.querySelectorAll(".fb-item")];
    const idx=items.indexOf(item);
    if(idx<0)return;
    let next=-1;
    if(e.key==="Home")next=0;
    else if(e.key==="End")next=items.length-1;
    else if(viewMode==="list"){
      if(e.key==="ArrowDown")next=Math.min(items.length-1,idx+1);
      else if(e.key==="ArrowUp")next=Math.max(0,idx-1);
    }else{
      if(e.key==="ArrowRight")next=Math.min(items.length-1,idx+1);
      else if(e.key==="ArrowLeft")next=Math.max(0,idx-1);
      else if(e.key==="ArrowDown" || e.key==="ArrowUp"){
        const firstTop=items[0].offsetTop;
        let cols=0;while(cols<items.length && items[cols].offsetTop===firstTop)cols++;
        cols=Math.max(1,cols);
        next=e.key==="ArrowDown"?Math.min(items.length-1,idx+cols):Math.max(0,idx-cols);
      }
    }
    if(next>=0 && next!==idx){e.preventDefault();items[next].focus();}
  };

  nativeBtn.onclick=async()=>{
    if(pickingNative)return;
    pickingNative=true;
    submit.disabled=true;
    const callSeq=++opSeq;
    nativeBtn.disabled=true;
    nativeBtn.setAttribute("aria-busy","true");
    $("formError").hidden=true;
    try{
      const res=await api("choose-directory",{path:input.value.trim()});
      if(openModalVersion!==modalVersion || !panel.isConnected || callSeq!==opSeq)return;
      if(res.status==="selected" && typeof res.path==="string" && res.path){
        input.value=res.path;
        closeBrowser(false);
        input.focus();
      }else if(res.status==="unavailable"){
        openBrowser(input.value.trim(),"本机目录选择器不可用，已切换为网页目录浏览。");
      }
    }catch(ex){
      if(openModalVersion===modalVersion && panel.isConnected && callSeq===opSeq)error(ex);
    }finally{
      pickingNative=false;
      if(!browserOpen)submit.disabled=false;
      if(nativeBtn.isConnected){nativeBtn.disabled=false;nativeBtn.removeAttribute("aria-busy");}
    }
  };

  webBtn.onclick=()=>{
    if(browserOpen)closeBrowser(true);
    else openBrowser(input.value.trim(),"");
  };
}
async function toggleClaude(){
  if(!data)return;
  const p=project;
  if(claudePending.has(p))return;
  const currentOn=data.seats.some(s=>s.agent==="claude");
  const target=currentOn?"off":"on";
  if(!currentOn && !data.claude_configured){claudeConfig(true);return;}
  const hadModeClaude=target==="off" && $("mode").value==="claude";
  const hadFocus=document.activeElement?.id==="claudeToggle";
  const token=++claudeSeq;
  claudePending.set(p,{target,from:currentOn,token});
  if(claudeErr && claudeErr.project===p)claudeErr=null;
  render();
  let toggled=false;
  try{
    await api("claude",{project:p,enabled:target});
    toggled=true;
  }catch(ex){
    const msg=ex?.message||"请求失败";
    if(project===p)claudeErr={project:p,message:"项目「"+p+"」Claude "+(target==="on"?"开启":"关闭")+"失败："+msg};
    else notify("项目「"+p+"」Claude "+(target==="on"?"开启":"关闭")+"失败："+msg);
  }
  if(toggled && project===p){
    try{await refresh();}
    catch(ex){claudeErr={project:p,message:"状态刷新失败："+(ex?.message||"请稍后重试")};}
  }
  if(claudePending.get(p)?.token===token)claudePending.delete(p);
  if(data)render();
  if(toggled && hadModeClaude && project===p && !data.seats.some(s=>s.agent==="claude")){
    notify("项目「"+p+"」已关闭 Claude，讨论方式已切回「共同讨论」。");
  }
  if(hadFocus && project===p && !$("modal").open)$("claudeToggle")?.focus();
}
function claudeConfig(enable){
  const p=project;
  const version=dialog("Claude 出口",'<form id="claudeForm"><label for="claudeIP">本机的公网 IPv4</label>'+
    '<input class="field" id="claudeIP" placeholder="例如 203.0.113.10" inputmode="decimal" autocomplete="off" '+(enable?'required':'')+'>'+
    '<p class="hint">只保存在运行圆桌的电脑上。启用后会在调用期间复查。</p><div class="dialogactions">'+
    (!enable && data.claude_configured?'<button class="quiet" id="clearIP" type="button">移除并关闭 Claude</button>':'')+
    '<button class="primary">'+(enable?'核验并开启':'保存')+'</button></div></form>');
  $("claudeIP").focus();
  async function save(value, button){
    button.disabled=true; $("formError").hidden=true;
    try{
      await api("claude-config",{project:p,ip:value});
      if(enable)await api("claude",{project:p,enabled:"on"});
      if(version===modalVersion)dismiss();
      await refresh();notify(enable?"已开启 Claude":value?"已保存出口设置":"已关闭 Claude 并移除核验地址");
    }catch(ex){if(version===modalVersion)error(ex);}
    finally{button.disabled=false;}
  }
  $("claudeForm").onsubmit=e=>{e.preventDefault(); const ip=$("claudeIP").value.trim();if(ip)save(ip,e.submitter);};
  if($("clearIP"))$("clearIP").onclick=e=>save("",e.currentTarget);
}
function showRecordFolder(id){
  const path=id?data.selected.folder:data.project_folder;
  dialog(id?"讨论文件夹":"项目记录文件夹",
    '<p class="hint">在文件管理器中移走对应的讨论文件夹后，圆桌会更新历史。项目工作目录单独保存。</p>'+
    '<label for="recordPath">位置</label><input readonly class="field" id="recordPath" value="'+esc(path)+'">'+
    '<div class="dialogactions"><button class="quiet" id="copyPath">复制路径</button>'+
    (data.native_folders?'<button class="primary" id="revealPath">在文件管理器打开</button>':'')+'</div>');
  $("copyPath").onclick=async()=>{try{await navigator.clipboard.writeText(path);notify("已复制路径");}catch{$("recordPath").select();}};
  if($("revealPath"))$("revealPath").onclick=async e=>{
    const b=e.currentTarget;b.disabled=true;
    try{await api("folder",{project,session:id||""});notify("已打开文件夹");}catch(ex){error(ex);}finally{b.disabled=false;}
  };
}
function resetTime(value){
  if(value==null)return "重置时间未提供";
  const date=new Date(typeof value==="number"?value*1000:value);
  return Number.isNaN(+date)?"重置时间未提供":new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}).format(date)+" 重置";
}
function formatClock(ts){
  if(ts==null)return "";
  const d=new Date(typeof ts==="number"?(ts>1e12?ts:ts*1000):ts);
  return Number.isNaN(+d)?"":d.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
}
const buckets={"gemini-5h":"Gemini · 5 小时","gemini-weekly":"Gemini · 每周","3p-5h":"Google 第三方模型池 · 5 小时","3p-weekly":"Google 第三方模型池 · 每周","gemini-argon-wtu-weekly":"Gemini Argon WTU · 每周"};
function health(){
  if(!data)return;
  const version=dialog("订阅额度",'<div id="quotaList"></div>'+
    '<p class="hint qnote">通过本机 CLI 读取账号额度，缓存 60 秒。刷新会重新查询。</p>'+
    '<div class="dialogactions"><button type="button" class="primary" id="refreshQuota" disabled>查询中…</button></div>');
  let inFlight=false;
  async function load(force){
    if(inFlight || version!==modalVersion || !data)return;
    inFlight=true;
    const reqSeq=++quotaSeq, reqProject=project, seats=data.seats.slice();
    const list=$("quotaList"), btn=$("refreshQuota");
    if(!list || !btn){inFlight=false;return;}
    $("formError").hidden=true;
    btn.disabled=true;
    btn.textContent=force?"正在刷新…":"查询中…";
    list.innerHTML=seats.map(s=>'<section class="qprovider"><div class="qtitle">'+glyph(s.agent)+'<b>'+labels[s.agent]+'</b><span class="qstate busy" id="quota-status-'+s.agent+'">'+(force?'正在刷新…':'正在查询…')+'</span></div><div id="quota-'+s.agent+'" class="qbody"><p class="hint">'+(force?'正在重新查询账号额度…':'正在查询账号额度…')+'</p></div></section>').join("");
    await Promise.allSettled(seats.map(async seat=>{
      try{
        const r=await api("quota?project="+encodeURIComponent(reqProject)+"&agent="+encodeURIComponent(seat.agent)+(force?"&refresh=1":""));
        if(version!==modalVersion || reqSeq!==quotaSeq || project!==reqProject)return;
        const body=$("quota-"+seat.agent), badge=$("quota-status-"+seat.agent);
        if(!body || !badge)return;
        const isStale=Boolean(r.stale);
        const isCached=!isStale && Boolean(r.cached);
        badge.className="qstate "+(isStale?"warn":isCached?"cached":"good");
        badge.textContent=isStale?"刷新失败":isCached?"已缓存":"额度查询成功";
        const order=w=>String(w.label||"").startsWith("gemini-5h")?0:w.label==="gemini-weekly"?1:2;
        const rows=(Array.isArray(r.windows)?r.windows:[]).slice().sort((a,b)=>order(a)-order(b));
        const rowsHtml=rows.length ? rows.map(w=>{
          const n=w.percent, title=buckets[w.label]||w.label;
          const empty=!w.disabled&&(typeof n==="number"?n<=0:w.amount===0);
          const low=!empty&&typeof n==="number"&&n<=10;
          return '<div class="qrow'+(empty||low?' quota-low':'')+'"><div><span>'+esc(title)+'</span><b>'+(empty?'额度已用完':w.disabled?'已停用':n==null?(w.amount==null?'可用':'剩余 '+esc(w.amount)):'剩余 '+esc(Number(n.toFixed(1)))+'%')+'</b></div>'+
            (n==null?'':'<meter min="0" max="100" value="'+esc(n)+'" aria-label="'+esc(title)+' 剩余额度"></meter>')+'<small>'+esc(resetTime(w.reset))+'</small></div>';
        }).join("") : '<p class="hint">暂无分段额度。</p>';
        const clock=formatClock(r.checked);
        const metaParts=[];
        if(r.plan)metaParts.push(esc(r.plan));
        if(clock)metaParts.push((isStale?"上次成功读取 ":isCached?"缓存于 ":"查询于 ")+esc(clock));
        body.innerHTML=rowsHtml+(metaParts.length?'<small class="qstamp">'+metaParts.join(" · ")+'</small>':'')+
          (isStale?'<p class="formerror">显示上次查询结果'+(r.error?'：'+esc(r.error):'')+'</p>':'');
      }catch(ex){
        if(version!==modalVersion || reqSeq!==quotaSeq || project!==reqProject)return;
        const body=$("quota-"+seat.agent), badge=$("quota-status-"+seat.agent);
        if(!body || !badge)return;
        badge.className="qstate err";
        badge.textContent="查询失败";
        body.innerHTML='<p class="formerror">账号额度查询失败'+(ex?.message?'：'+esc(ex.message):'')+'</p>';
      }
    }));
    inFlight=false;
    if(version===modalVersion && reqSeq===quotaSeq){
      if(project!==reqProject){load(false);return;}
      if($("refreshQuota")){
        $("refreshQuota").disabled=false;
        $("refreshQuota").textContent="刷新额度";
      }
    }
  }
  $("refreshQuota").onclick=()=>load(true);
  load(false);
}
function runDialog(){
  const p=project, id=sid;
  dialog("按分工实施",'<form id="runForm"><label for="runPath">实施目录</label><input class="field" id="runPath" value="'+esc(data.path)+'" placeholder="输入已有项目目录" required><p class="hint">各负责人将按方案顺序在此目录工作，上一项的报告会交给下一席。</p><div class="dialogactions"><button class="primary">开始实施</button></div></form>');
  directoryPicker("runPath");
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
    if(b.dataset.permission){
      b.dataset.busy="true"; b.disabled=true; b.textContent="正在提交…";
      try{await api("permission",{project,session:sid,request:b.dataset.permission,decision:b.dataset.choice});}
      finally{delete b.dataset.busy;await refresh();if(b.isConnected && data.selected){b.disabled=false;renderDiscussion(data.selected);}}
      return;
    }
    if(b.id==="jumpReply"){$("topic").focus();return;}
    if(b.id==="failureQuota"){health();return;}
    if(b.id==="discussionFolder"){showRecordFolder(sid);return;}
    if(b.id==="projectFolder"){showRecordFolder();return;}
    if(b.dataset.live){await navigate(b.dataset.owner,b.dataset.live);return;}
    if(b.id==="stop"){b.disabled=true;await api("stop",{project,session:sid});await refresh();return;}
    if(b.hasAttribute("data-claude-toggle")){await toggleClaude();return;}
    if(b.dataset.agent){await pickModel(b.dataset.agent);return;}
    if(b.dataset.project){const p=b.dataset.project;await api("project",{project,action:"use",name:p});await navigate(p,null);return;}
    if(b.dataset.session){await navigate(project,b.dataset.session);return;}
    if(b.id==="exportPDF"){
      const id=sid,p=project;b.disabled=true;
      try{
        if(!data.selected.has_pdf){b.textContent="Gemini 正在排版…";await api("pdf",{project:p,session:id});}
        const response=await fetch("/api/pdf?"+new URLSearchParams({project:p,session:id}),{headers:{"X-Roundtable":key}});
        if(!response.ok)throw Error((await response.json()).error);
        const url=URL.createObjectURL(await response.blob()), link=document.createElement("a");
        link.href=url;link.download=p+"-"+id+".pdf";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }finally{await refresh();}
      return;
    }
    if(b.id==="exportRecord" || b.id==="exportPlan"){
      const id=sid, plan=b.id==="exportPlan";
      const markdown=plan ? (finalDraft(data.selected)||("# "+project+" · "+states[data.selected.state]+"\n\n"+data.selected.plan))+"\n"
                          : (await api("record?"+new URLSearchParams({project,session:id}))).markdown;
      const url=URL.createObjectURL(new Blob([markdown],{type:"text/markdown;charset=utf-8"}));
      const link=document.createElement("a");link.href=url;link.download=(plan?"方案-":"圆桌-")+id+".md";link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
    if(b.id==="continueDispute"){
      $("mode").value="both";
      if(!$("topic").value.trim())$("topic").value="请保留上一版已同意的部分，逐条回应最后表决中的阻塞异议，并说明怎样验证修订。";
      saveDraft();$("topic").focus();return;
    }
    if(b.id==="resumeDiscussion"){
      b.disabled=true;const id=sid, p=project;
      const task=api("resume",{project:p,session:id});
      const timer=setTimeout(()=>{if(project===p && sid===id)refresh().catch(error);},400);
      try{await task;}finally{clearTimeout(timer);await refresh();}
      return;
    }
    if(b.id==="implement")runDialog();
  }catch(ex){error(ex);}
});
$("composer").onsubmit=async e=>{
  e.preventDefault();const topic=$("topic").value.trim();if(!topic||pending||!data||ongoing(data.selected?.state))return;
  if($("mode").value==="claude" && !data.seats.some(s=>s.agent==="claude")){
    $("mode").value="both";render();notify("当前项目未开启 Claude，讨论方式已切回「共同讨论」。");return;
  }
  const p=project, parent=sid;pending=true;render();
  try{
    const next=await api("start",{project:p,session:parent||"",topic,mode:$("mode").value,moderator:$("moderator").value});
    if(project===p&&sid===parent){$("topic").value="";await navigate(p,next.session);}
  }catch(ex){error(ex);}finally{pending=false;if(data)render();}
};
$("topic").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey)&&!e.isComposing){e.preventDefault();$("composer").requestSubmit();}});
$("new").onclick=async()=>{$("mode").value="both";await navigate(project,null);$("topic").focus();};
$("mode").onchange=()=>{if(data)render();};
$("reconnect").onclick=()=>refresh().catch(error);
document.addEventListener("visibilitychange",()=>{if(document.hidden)clearTimeout(poll);else refresh().catch(error);});
$("settings").onclick=()=>projectDialog(false);$("add").onclick=()=>projectDialog(true);$("health").onclick=()=>health();
$("menu").onclick=()=>{document.body.classList.add("navopen");$("closeNav").focus();};$("closeNav").onclick=closeNav;$("scrim").onclick=closeNav;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeNav();});
refresh().then(()=>{$("topic").value=readDraft();}).catch(error);
