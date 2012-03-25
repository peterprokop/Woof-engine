import cgi
import datetime
import time
import logging

from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import images

from django.utils import simplejson

logging.getLogger().setLevel(logging.DEBUG)

def to_dict(model):
    simple_types = (int, long, float, bool, dict, basestring, list)
    base_url = 'http://localhost:8080/img?img_id='
    output = {}

    for key, prop in model.properties().iteritems():
        value = getattr(model, key)
        if isinstance(prop, db.BlobProperty):
            try:
                url = base_url + str(model.key())
                image = images.Image(value) # This is very unproductive
                output[key] = {'url':url, 'width':image.width, 'height':image.height}
            except images.NotImageError:
                continue
        elif value is None or isinstance(value, simple_types):
            output[key] = value
        elif isinstance(value, datetime.date):
            # Convert date/datetime to timestamp
            ms = time.mktime(value.utctimetuple()) 
            ms += getattr(value, 'microseconds', 0) / 1000
            output[key] = int(ms)
        elif isinstance(value, db.GeoPt):
            output[key] = {'lat': value.lat, 'lon': value.lon}
        elif isinstance(value, db.Model):
            output[key] = to_dict(value)
        else:
            raise ValueError('Cannot encode ' + repr(prop))

    return output


class FeedItem(db.Model):
	author = db.UserProperty()
	text = db.StringProperty(multiline=True)
	avatar = db.BlobProperty()
	date = db.DateTimeProperty(auto_now_add=True)

class MainPage(webapp.RequestHandler):
	def get(self):
		self.response.out.write('<html><body>')
		query_str = "SELECT * FROM FeedItem ORDER BY date DESC LIMIT 10"
		greetings = db.GqlQuery (query_str)

		for greeting in greetings:
			if greeting.author:
				self.response.out.write('<b>%s</b> wrote:' % greeting.author.nickname())
			else:
				self.response.out.write('An anonymous person wrote:')
			self.response.out.write("<div><img src='img?img_id=%s'></img>" %
									greeting.key())
			self.response.out.write(' %s</div>' %
								  cgi.escape(greeting.text))

		self.response.out.write("""
			  <form action="/sign" enctype="multipart/form-data" method="post">
				<div><label>Message:</label></div>
				<div><textarea name="text" rows="3" cols="60"></textarea></div>
				<div><label>Avatar:</label></div>
				<div><input type="file" name="img"/></div>
				<div><input type="submit" value="Sign Guestbook"></div>
			  </form>
			</body>
		  </html>""")

class Image (webapp.RequestHandler):
	def get(self):
		greeting = db.get(self.request.get("img_id"))
		if greeting.avatar:
			self.response.headers['Content-Type'] = "image/png"
			self.response.out.write(greeting.avatar)
		else:
			self.response.out.write("No image")

class Guestbook(webapp.RequestHandler):
	def post(self):
		greeting = FeedItem()
		if users.get_current_user():
			greeting.author = users.get_current_user()
		greeting.text = self.request.get("text")
		avatar = images.resize(self.request.get("img"), width = 320, output_encoding = images.JPEG)
		greeting.avatar = db.Blob(avatar)
		greeting.put()
		self.redirect('/')

class APIFeed(webapp.RequestHandler):
    def get(self):
        query_str = "SELECT * FROM FeedItem ORDER BY date DESC LIMIT 10"
        feed_items = db.GqlQuery(query_str).fetch(10)
        self.response.headers['Content-Type'] = "application/json"
        feed_items_serialized = []
        for item in feed_items:
            feed_items_serialized.append(to_dict(item));    
        self.response.out.write(simplejson.dumps(feed_items_serialized))

        
application = webapp.WSGIApplication([
	('/', MainPage),
	('/img', Image),
	('/sign', Guestbook),
	('/api/feed', APIFeed)
], debug=True)

def main():
	run_wsgi_app(application)
	
if __name__ == '__main__':
	main()