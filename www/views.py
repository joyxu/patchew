from django.shortcuts import render
from django.template import Context
from django.http import HttpResponse, Http404
from django.core.urlresolvers import reverse
import api
from mod import dispatch_module_hook

PAGE_SIZE = 50

def render_page(request, template_name, **data):
    dispatch_module_hook("render_page_hook", context_data=data)
    return render(request, template_name, context=data)

def prepare_message(m):
    name, addr = m.get_sender()
    m.sender_full_name = "%s <%s>" % (name, addr)
    m.sender_display_name = name or addr
    m.url = "/%s/%s" % (m.project.name, m.message_id)
    m.status_tags = []
    if m.is_series_head:
        m.num_patches = len(m.get_patches())
        if m.get_num():
            m.total_patches = m.get_num()[1] or 1
        else:
            m.total_patches = 1
        if m.num_patches < m.total_patches:
            m.status_tags.append({
                "title": "Series not complete (%d patches not received)" % \
                        (m.total_patches - m.num_patches),
                "type": "warning",
                "char": "P",
                })
    m.extra_info = []
    m.extra_headers = []
    dispatch_module_hook("prepare_message_hook", message=m)
    return m

def prepare_series(s):
    r = []
    def add_msg_recurse(m, depth=0):
        a = prepare_message(m)
        a.indent_level = min(depth, 4)
        r.append(prepare_message(m))
        replies = m.get_replies()
        non_patches = [x for x in replies if not x.is_patch]
        patches = [x for x in replies if x.is_patch]
        for x in non_patches + patches:
            add_msg_recurse(x, depth+1)
        return r
    add_msg_recurse(s)
    return r

def prepare_series_list(sl):
    return [prepare_message(s) for s in sl]

def prepare_projects():
    return api.models.Project.objects.all()

def view_project_list(request):
    return render_page(request, "project-list.html", projects=prepare_projects)

def gen_page_links(total, cur_page, pagesize):
    max_page = (total + pagesize - 1) / pagesize
    ret = []
    ddd = False
    for i in range(1, max_page + 1):
        if i == cur_page:
            ret.append({
                "title": str(i),
                "url": "?page=" + str(i),
                "class": "active",
                "url": "#"
                })
            ddd = False
        elif i < 10 or abs(i - cur_page) < 3 or max_page - i < 3:
            ret.append({
                "title": str(i),
                "url": "?page=" + str(i),
                })
            ddd = False
        else:
            if not ddd:
                ret.append({
                    "title": '...',
                    "class": "disabled",
                    "url": "#"
                    })
                ddd = True

    return ret

def get_page_from_request(request):
    try:
        return int(request.GET["page"])
    except:
        return 1

def prepare_navigate_list(cur, *path):
    """ each path is (view_name, kwargs, title) """
    r = [{"url": reverse("project_list"),
          "title": "Projects"}]
    for it in path:
        r.append({"url": reverse(it[0], kwargs=it[1]),
                  "title": it[2]})
    r.append({"title": cur})
    return r

def render_series_list_page(request, query, search, project=None, keywords=[]):
    sort = request.GET.get("sort")
    if sort == "replied":
        sortfield = "-last_reply_date"
        order_by_reply = True
    else:
        sortfield = "-date"
        order_by_reply = False
    if sortfield:
        query = query.order_by(sortfield)
    cur_page = get_page_from_request(request)
    start = (cur_page - 1) * PAGE_SIZE
    series = query[start:start + PAGE_SIZE]
    page_links = gen_page_links(query.count(), cur_page, PAGE_SIZE)
    if project:
        nav_path = prepare_navigate_list("Patches",
                                         ("project_detail", {"project": project}, project))
    else:
        nav_path = prepare_navigate_list('search "%s"' % search)
    return render_page(request, 'series-list.html',
                       series=prepare_series_list(series),
                       page_links=page_links,
                       search=search,
                       keywords=keywords,
                       project_column=project==None,
                       order_by_reply=order_by_reply,
                       navigate_links=nav_path)

def view_search_help(request):
    from markdown import markdown
    nav_path = prepare_navigate_list("Search help")
    return render_page(request, 'search-help.html',
                       navigate_links=nav_path,
                       search_help_doc=markdown(api.search.SearchEngine.__doc__))

def view_project_detail(request, project):
    po = api.models.Project.objects.filter(name=project).first()
    if not po:
        raise Http404("Project not found")
    nav_path = prepare_navigate_list("Information",
                        ("project_detail", {"project": project}, project))
    return render_page(request, "project-detail.html",
                       project=po,
                       navigate_links=nav_path,
                       search="")

def view_search(request):
    from api.search import SearchEngine
    search = request.GET.get("q", "").strip()
    terms = [x.strip() for x in search.split(" ") if x]
    se = SearchEngine()
    query = se.search_series(*terms)
    return render_series_list_page(request, query, search,
                                   keywords=se.last_keywords())

def view_series_list(request, project):
    if not api.models.Project.has_project(project):
        raise Http404("Project not found")
    search = "project:%s" % project
    query = api.models.Message.objects.series_heads(project)
    return render_series_list_page(request, query, search, project=project)

def view_series_mbox(request, project, message_id):
    s = api.models.Message.objects.find_series(message_id, project)
    if not s:
        raise Http404("Series not found")
    r = prepare_series(s)
    mbox = "\n".join([x.get_mbox() for x in r])
    return HttpResponse(mbox, content_type="text/plain")

def view_series_detail(request, project, message_id):
    s = api.models.Message.objects.find_series(message_id, project)
    if not s:
        raise Http404("Series not found")
    nav_path = prepare_navigate_list(s.message_id,
                    ("series_list", {"project": project}, project))
    search = "id:" + message_id
    ops = []
    dispatch_module_hook("www_series_operations_hook",
                         request=request,
                         series=s,
                         operations=ops)
    return render_page(request, 'series-detail.html',
                       series=prepare_message(s),
                       project=project,
                       navigate_links=nav_path,
                       search=search,
                       series_operations=ops,
                       messages=prepare_series(s))
