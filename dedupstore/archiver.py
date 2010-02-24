import os
import sys
import hashlib
import zlib
import cPickle
from optparse import OptionParser

from store import Store

CHUNKSIZE = 256 * 1024
NS_ARCHIVES = 'ARCHIVES'
NS_CHUNKS  = 'CHUNKS'

class Cache(object):
    """Client Side cache
    """
    def __init__(self, path, store):
        self.store = store
        self.path = path
        self.tid = -1
        self.open()
        if self.tid != self.store.tid:
            print self.tid, self.store.tid
            self.create()

    def open(self):
        if self.store.tid == -1:
            return
        filename = os.path.join(self.path, '%s.cache' % self.store.uuid)
        if not os.path.exists(filename):
            return
        print 'Reading cache: ', filename, '...'
        data = cPickle.loads(zlib.decompress(open(filename, 'rb').read()))
        self.chunkmap = data['chunkmap']
        self.tid = data['tid']
        print 'done'

    def create(self):
        self.chunkmap = {}
        self.tid = self.store.tid
        if self.store.tid == 0:
            return
        print 'Recreating cache...'
        for id in self.store.list(NS_ARCHIVES):
            archive = cPickle.loads(zlib.decompress(self.store.get(NS_ARCHIVES, id)))
            for item in archive['items']:
                if item['type'] == 'FILE':
                    for c in item['chunks']:
                        self.chunk_incref(c)
        print 'done'

    def save(self):
        assert self.store.state == Store.OPEN
        print 'saving cache'
        data = {'chunkmap': self.chunkmap, 'tid': self.store.tid}
        filename = os.path.join(self.path, '%s.cache' % self.store.uuid)
        print 'Saving cache as:', filename
        with open(filename, 'wb') as fd:
            fd.write(zlib.compress(cPickle.dumps(data)))
        print 'done'

    def add_chunk(self, data):
        hash = hashlib.sha1(data).digest()
        if not self.seen_chunk(hash):
            self.store.put(NS_CHUNKS, hash, data)
        else:
            print 'seen chunk', hash.encode('hex')
        self.chunk_incref(hash)
        return hash

    def seen_chunk(self, hash):
        return self.chunkmap.get(hash, 0) > 0

    def chunk_incref(self, hash):
        self.chunkmap.setdefault(hash, 0)
        self.chunkmap[hash] += 1

    def chunk_decref(self, hash):
        count = self.chunkmap.get(hash, 0) - 1
        assert count >= 0
        self.chunkmap[hash] = count
        if not count:
            print 'deleting chunk: ', hash.encode('hex')
            self.store.delete(NS_CHUNKS, hash)
        return count


class Archiver(object):

    def __init__(self):
        self.store = Store('/tmp/store')
        self.cache = Cache('/tmp/cache', self.store)

    def create_archive(self, archive_name, paths):
#        if archive_name in self.cache.archives:
#            raise Exception('Archive "%s" already exists' % archive_name)
        items = []
        for path in paths:
            for root, dirs, files in os.walk(path):
                for d in dirs:
                    name = os.path.join(root, d)
                    items.append(self.process_dir(name, self.cache))
                for f in files:
                    name = os.path.join(root, f)
                    items.append(self.process_file(name, self.cache))
        archive = {'name': archive_name, 'items': items}
        hash = self.store.put(NS_ARCHIVES, archive_name, zlib.compress(cPickle.dumps(archive)))
        self.store.commit()
        self.cache.save()

    def delete_archive(self, archive_name):
        archive = cPickle.loads(zlib.decompress(self.store.get(NS_ARCHIVES, archive_name)))
        self.store.delete(NS_ARCHIVES, archive_name)
#        if not hash:
#            raise Exception('Archive "%s" does not exist' % archive_name)
        for item in archive['items']:
            if item['type'] == 'FILE':
                for c in item['chunks']:
                    self.cache.chunk_decref(c)
        self.store.commit()
        self.cache.save()

    def process_dir(self, path, cache):
        print 'Directory: %s' % (path)
        return {'type': 'DIR', 'path': path}

    def process_file(self, path, cache):
        fd = open(path, 'rb')
        size = 0
        chunks = []
        while True:
            data = fd.read(CHUNKSIZE)
            if not data:
                break
            size += len(data)
            chunks.append(cache.add_chunk(zlib.compress(data)))
        print 'File: %s (%d chunks)' % (path, len(chunks))
        return {'type': 'FILE', 'path': path, 'size': size, 'chunks': chunks}
    
    def run(self):
        parser = OptionParser()
        parser.add_option("-C", "--cache", dest="cache",
                          help="cache directory to use", metavar="CACHE")
        parser.add_option("-s", "--store", dest="store",
                          help="path to dedupe store", metavar="STORE")
        parser.add_option("-c", "--create", dest="create_archive",
                          help="create ARCHIVE", metavar="ARCHIVE")
        parser.add_option("-d", "--delete", dest="delete_archive",
                          help="delete ARCHIVE", metavar="ARCHIVE")
        parser.add_option("-l", "--list-archives", dest="list_archives",
                        help="list archives")
        parser.add_option("-V", "--verify", dest="verify_archive",
                        help="verify archive consistency")
        parser.add_option("-e", "--extract", dest="extract_archive",
                        help="extract ARCHIVE")
        parser.add_option("-L", "--list-archive", dest="list_archive",
                        help="verify archive consistency", metavar="ARCHIVE")
        (options, args) = parser.parse_args()
        if options.delete_archive:
            self.delete_archive(options.delete_archive)
        else:
            self.create_archive(options.create_archive, args)

def main():
    archiver = Archiver()
    archiver.run()

if __name__ == '__main__':
    main()