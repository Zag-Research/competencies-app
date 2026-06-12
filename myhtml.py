from html import escape as htmlEscape
def escape(arg):
	if type(arg)==str: return htmlEscape(arg)
	return str(arg)
def attribute(k,v):
	k=k.replace('_','-')
	if k[0]=='-': k=k[1:]
	if v==True: return k
	return '{}="{}"'.format(k,escape(v).replace('"','&quot;'))

class element():
	def __init__(self,*args,**kw):
		self.content=[arg for arg in args]
		self.keywords=kw
		self.tag=type(self).__name__
		self.classList=None
		self.preTag=''
		self.postTag=''
	def parenthesize(self,first='(',last=')'):
		self.preTag=first
		self.postTag=last
	def __str__(self):
		return '{0}<{1}{2}>{3}{4}{5}'.format(self.preTag,self.tag,self.options(),self.contents(),self.endTag(),self.postTag)
	def endTag(self):
		return '</'+self.tag+'>'
	def classes(self,*args):
		self.classList=args
		return self
	def addAttributes(self,**kw):
		for key,value in kw.items():
			self.keywords[key]=value
		return self
	def addClasses(self,*args):
		if self.classList:
			self.classList+=args
		else:
			self.classList=args
		return self
	def options(self):
		if self.classList: self.keywords['class']=' '.join(self.classList)
		return ' '+' '.join([attribute(k,v) for k,v in self.keywords.items()]) if self.keywords else ''
	def contents(self):
		return '\n'.join([escape(e) for e in self.content])
	def __iadd__(self,arg):
		if arg not in self.content:
			self.content.append(arg)
		return self
	def add(self,*args):
		for arg in args:
			self += arg

class html(element):
	pass
'''	def __str__(self):
		return """<!DOCTYPE html>
"""+super.__str__()'''
class p(element):
	pass
class div(element):
	pass
class head(element):
	pass
class body(element):
	pass
class meta(element):
	def endTag(self): return ''
class link(element):
	def endTag(self): return ''
class br(element):
	def endTag(self): return ''
class title(element):
	pass
class script(element):
	pass
class span(element):
	pass
class form(element):
	pass
class input(element):
	pass
class button(element):
	pass
class pre(element):
	pass
class table(element):
	pass
class thead(element):
	pass
class tbody(element):
	pass
class tr(element):
	pass
class th(element):
	pass
class td(element):
	def addPerson(self,person,assigned,rank,html):
		self += html
class a(element):
	pass
class script(element):
	pass

class page():
	def __init__(self):
		self.head=head(
			meta(http_equiv="Content-Type",content="text/html; charset=UTF-8"),
			meta(name="keywords",content="Toronto Metropolitan University Computer Science Admin"),
			title("Computer Science Admin"),
			)
		self.body=body()
		self.html=html(self.head,self.body,xmlns="http://www.w3.org/1999/xhtml")#.classes('mine','other')
		self.css="/static/css/main.css"
		self.js="/static/js/header.js"
	def setCss(self,str):
		self.css=str
	def setJs(self,str):
		self.js=str
	def add(self,*content):
		self.body.add(*content)
	def __iadd__(self,other):
		self.body.add(other)
		return self
	def __str__(self):
		if self.css: self.head.add(link(rel="stylesheet",type="text/css",media="all",href=self.css))
		if self.js: self.head.add(script(defer=True,src=self.js))
		return str(self.html)

#if __file__=='__main__':
#print(html('abc',3,foo='bar',blat=42).text())
