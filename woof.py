#!/usr/bin/env python
#
# Copyright 2012 Woof Inc.
#
# This wonderful piece of software is distributed under Woof licence.
#
# You may download, read, execute and modify this file if and only if
# you adore, worship, idolize and deify lolcats (and supported witty texts).
#
# You MAY NOT download, read, execute (and, of course, modify) 
# this file (and supported witty texts) otherwise.
#

from config import *

import cgi
import datetime
import time
import logging
import urllib

from google.appengine.ext import db
from google.appengine.ext import blobstore
from google.appengine.ext import webapp
from google.appengine.ext.blobstore import BlobInfo
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext.webapp.util import run_wsgi_app

from google.appengine.api import users
from google.appengine.api import images
from google.appengine.api.images import IMG_SERVING_CROP_SIZES
from google.appengine.api import files

# For some reason this is not working under python27
#from django.utils import simplejson
from google.appengine._internal.django.utils import simplejson

logging.getLogger().setLevel(logging.DEBUG)

def to_dict(model):
    simple_types = (int, long, float, bool, dict, basestring, list)
    # Replace it with image serving url
    base_url = 'http://localhost:8080/img?img_id='
    output = {}

    # Check if object can convert itself to dictionary
    if(hasattr(model,"to_dict")):
        return model.to_dict()
        
    for key, prop in model.properties().iteritems():
        value = getattr(model, key)
        # Assuming that BLOB is always an image
        if isinstance(prop, blobstore.BlobReferenceProperty):
            try:
                url = images.get_serving_url(value.key())
                output['url'] = url
            except images.NotImageError:
                continue
        # Assuming that BLOB is always an image
        elif isinstance(prop, db.BlobProperty):
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
    
class FeedImage(db.Model):
    data = blobstore.BlobReferenceProperty(required=False)
    width = db.IntegerProperty()
    height = db.IntegerProperty()
    
    def to_dict(self):
        url = images.get_serving_url(self.data.key())
        thumbnail_size = IMG_SERVING_CROP_SIZES[5]; # = 104
        thumbnail_url = images.get_serving_url(self.data.key(), size = thumbnail_size, crop = True) 
        return {
                'height':self.height,
                'width':self.width,
                'url':url,
                'thumbnails':[{
                                'url':thumbnail_url, 
                                'width':thumbnail_size, 
                                'height':thumbnail_size}],
                }
    
    
class FeedItem(db.Model):
    text = db.StringProperty(multiline=True)
    date = db.DateTimeProperty(auto_now_add=True)
    image = db.ReferenceProperty(FeedImage)

class MainPage(webapp.RequestHandler):
    def get(self):
        self.response.out.write('<html><body>')
        query_str = "SELECT * FROM FeedItem ORDER BY date DESC LIMIT 10"
        feed_items = db.GqlQuery (query_str)

        for feed_item in feed_items:
            self.response.out.write("<div>")
               
            if(feed_item.image):
                self.response.out.write("<img src='/serve/%s'></img>" %
                                        feed_item.image.data.key())
            self.response.out.write("</div>")
            if(feed_item.text):
                self.response.out.write("<div>")
                self.response.out.write(feed_item.text)
                self.response.out.write("</div>")

            
        upload_url = blobstore.create_upload_url('/api/upload_image')
        self.response.out.write('<form action="%s" method="POST" enctype="multipart/form-data">' % upload_url)
        self.response.out.write("""
                <div><label>Text:</label></div>
                <div><textarea name="text" rows="3" cols="60"></textarea></div>
                <div><label>Image:</label></div>
                <div><input type="file" name="file"/></div>
                <div><input type="submit" value="Add!"></div>
              </form>
            </body>
          </html>""")

class Image (webapp.RequestHandler):
    def get(self):
        image = db.get(self.request.get("img_id"))
        if image.image.data:
            self.response.headers['Content-Type'] = "image/png"
            self.response.out.write(image.image.data)
        else:
            self.response.out.write("No image")

class APIFeed(webapp.RequestHandler):
    def get(self):
        query_str = "SELECT * FROM FeedItem ORDER BY date DESC LIMIT 10"
        feed_items = db.GqlQuery(query_str).fetch(10)
        self.response.headers['Content-Type'] = "application/json"
        feed_items_serialized = []
        for item in feed_items:
            feed_items_serialized.append(to_dict(item));    
        self.response.out.write(simplejson.dumps(feed_items_serialized))

class APIUploadImage(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        upload_files = self.get_uploads('file')  
        blob_info = upload_files[0]
        # Resize the image
        image = images.Image(blob_key=blob_info.key())
        image.resize(width=WOOF_FEED_ITEM_IMAGE_MAX_WIDTH, height=WOOF_FEED_ITEM_IMAGE_MAX_HEIGHT)
        thumbnail = image.execute_transforms(output_encoding=images.JPEG)
        # Save Resized Image back to blobstore
        file_name = files.blobstore.create(mime_type='image/jpeg')
        with files.open(file_name, 'a') as f:
            f.write(thumbnail)
        files.finalize(file_name)
        # Remove the original image
        blobstore.delete(blob_info.key())
        blob_key = files.blobstore.get_blob_key(file_name)
        # New FeedImage
        feed_image = FeedImage()
        feed_image.data = BlobInfo.get(blob_key)
        feed_image.width = image.width
        feed_image.height = image.height
        feed_image.put()
        # Create new FeedItem
        feed_item = FeedItem()
        feed_item.text = self.request.get("text")
        feed_item.image = feed_image
        feed_item.put()
        self.redirect('/')

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, resource):
        resource = str(urllib.unquote(resource))
        blob_info = blobstore.BlobInfo.get(resource)
        self.send_blob(blob_info)        
   
application = webapp.WSGIApplication([
    ('/', MainPage),
    ('/img', Image),
	('/api/upload_image', APIUploadImage),
    ('/api/feed', APIFeed),
    ('/serve/([^/]+)?', ServeHandler)
], debug=True)

def main():
    run_wsgi_app(application)
    
if __name__ == '__main__':
    main()