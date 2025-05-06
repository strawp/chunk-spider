#!/usr/bin/python3
# Recursively download chunked JS files

import argparse, sys, re, time, signal, requests, urllib3, hashlib
import os.path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
urllib3.disable_warnings()

class Resource:
  url = None
  content = None
  proxies = None
  contenttype = None
  paths = []
  
  def __init__( self, url, proxy=None ):
    self.url = url
    if proxy:
      self.proxies = {
        'http': proxy,
        'https': proxy
      }
  
  def fetch( self ):
    response = requests.get( self.url, proxies=self.proxies, verify=False, allow_redirects=True )
    if not response or not response.content: raise Exception("No file content found")
    if not str( response.status_code ).startswith('2'): raise Exception(str(response.status_code) + ' returned')
    self.content = response.content.decode()
    self.contenttype = response.headers.get('content-type')

    # Hash the content
    hash_object = hashlib.sha256(response.content)
    self.hash = hash_object.hexdigest()
    
    if 'javascript' in self.contenttype:
      self.__class__ = JsFile
    else:
      self.__class__ = HtmlFile
    return response

class HtmlFile( Resource ):
  jsfiles = []
  inlinejs = []
  js = None

  def parse( self ):
    
    # Fetch all references to JS files
    if not self.content:
      self.fetch()

    soup = BeautifulSoup( self.content, 'html.parser' )
    for script in soup.find_all('script'):
      src = script.get('src')
      if src: self.jsfiles.append( src )
      else: self.inlinejs.append( script.content )

    if len( ''.join( self.inlinejs ).strip() ) > 0:
      self.js = JsFile( self.url )
      self.js.content = ''.join( self.inlinejs ).strip()
      self.js.parse()

  def get_js_urls( self ):
    rtn = []
    url = urlparse( self.url )

    # Directly referenced files
    for f in self.jsfiles:
      
      # Same protocol
      if f.startswith('//'):
        rtn.append( url.scheme + ':' + f)
        continue

      # Same host
      if f.startswith('/'):
        rtn.append( url.scheme + '://' + url.netloc + f )
        continue

      # Relative to current URL
      rtn.append( url.scheme + '://' + url.netloc + os.path.join( os.path.dirname( url.path ), f ) )

    # URLs guessed from inline JS
    if self.js:
      rtn = rtn + js.get_js_urls()

    rtn = list( set( rtn ) )
    print( 'Found in HTML:\n', rtn )
    return rtn

class JsFile( Resource ):
  chunks = []
  paths = []

  def parse( self ):
    if not self.content:
      self.fetch()
    
    # Look for chunk dicts e.g. 
    # {9:"26454eb9ee6ea13543d9",93:"45fc526fb568708f9e75",143:"2db0078a50b60395832c",147:"639b3f4b2cece83f1dc6",196:"1935d7ca83c8c9f78d35",357:"c1aa5f68360b6152eee8",388:"2adc4ed40e19b760d6be",524:"ca3102c97c465e7d5bb9",538:"4f19f7c83859794eec0b",559:"754996081bd3dfb26c53",657:"e4e1530c94a831b372f6",708:"e48e8422b639e111336a",841:"ab409098350a39745824",872:"03afec38607d98403ddf",895:"aa50b9bbf6c2234a2257",964:"55b95372a229e9114c93"}
    chunkpattern = r'((\d+) *: *"([a-f0-9]{20}|[a-z][a-zA-Z0-9]+)")+,?'
    self.chunks = [(x[1],x[2]) for x in re.findall(chunkpattern, self.content)]
    
    # Looks for something which could be a path
    pathpattern = r'"(/[:_/a-zA-Z0-9.?=&-]+)"'
    self.paths = re.findall(pathpattern, self.content)

    print(self.chunks, self.paths)
  
  def get_js_urls( self ):
    rtn = []
    url = urlparse( self.url )
    dirname = os.path.dirname( url.path )
    lookup = {}
    for chunk in self.chunks:
      if re.search(r'[a-f0-9]{20}',chunk[1]):
        lookup[chunk[0]] = chunk[1]

    print( lookup )
    
    for chunk in self.chunks:
      if not re.search(r'[a-f0-9]{20}',chunk[1]) and chunk[0] in lookup:
        self.chunks.append((chunk[1],lookup[chunk[0]]))
    
    for chunk in self.chunks:
      dirname = url.scheme + '://' + url.netloc + os.path.dirname( url.path )
      rtn.append( dirname + '/' + chunk[0] + '.' + chunk[1] + '.js' )
    return list( set( rtn ) )

class ChunkSpider:
  
  foundfiles = []
  foundpaths = []
  hashes = []
  proxy = None

  def __init__( self, proxy=None ):
    self.proxy = proxy

  def spider_url( self, url ):
    
    res = Resource( url, proxy=self.proxy )
    res.fetch()
    if res.hash in self.hashes: return
    self.hashes.append( res.hash )
    res.parse()
    self.foundpaths = list(set( self.foundpaths + res.paths))
    print('Paths:\n',self.foundpaths)
    for jsurl in res.get_js_urls():
      print('Currently known URLs:', self.foundfiles )
      if jsurl in self.foundfiles: 
        print('Skipping', jsurl )
        continue
      print( 'Testing new JS URL:', jsurl )
      self.spider_url( jsurl )
      self.foundfiles.append( jsurl )
    self.foundfiles = list( set( self.foundfiles ) )
    self.foundpaths = list( set( self.foundpaths ) )


def main():
  
  parser = argparse.ArgumentParser(description="Recursively download chunked JS files")
  parser.add_argument("--proxy", help="URL of HTTP proxy to send requests through, e.g. http://localhost:8080")
  parser.add_argument("url", help="URL or file containing list of URLs protected by basic auth")

  # Only fetch for these hosts
  args = parser.parse_args()

  spider = ChunkSpider( args.proxy )
  spider.spider_url( args.url )
  print('\nSearched these URLs:\n')
  print('\n'.join(spider.foundfiles))
  print('\nThe following look like paths:\n')
  print('\n'.join(spider.foundpaths))

if __name__ == '__main__':
  main()
