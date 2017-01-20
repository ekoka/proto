# coding=utf8
from threading import Lock
from functools import partial
try:
    from greenlet import get_ident
except ImportError:
    from threading import current_thread
    get_ident = lambda: current_thread().ident

from sqlalchemy import orm, event, create_engine
from sqlalchemy.event import listen
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta


class BaseQuery(orm.Query):
    pass # TODO

class _BoundDeclarativeMeta(DeclarativeMeta):
    def __init__(cls, name, bases, attr):
        bind_key = attr.pop('__bind_key__', None)
        super(_BoundDeclarativeMeta, cls).__init__(name, bases, attr)
        if bind_key is not None:
            cls.__table__.info['bind_key'] = bind_key

class BaseModel(object):
    query_class = BaseQuery
    query = None
  
class _QueryProperty(object):

    def __init__(self, db):
        self.db = db

    def __get__(self, obj, cls):
        try:
            orm.class_mapper(cls)
            return cls.query_class(cls, session=self.db.session())
        except orm.exc.UnmappedClassError:
            return None

class BaseSession(orm.session.Session):

    def __init__(self, db, autocommit=False, autoflush=True, **options):
        self.db = db
        super(BaseSession, self).__init__(
            autocommit=autocommit, 
            autoflush=autoflush, 
            **options)

    def get_bind(self, mapper, clause=None):
        # mapper is None if someone tries to just get a connection
        if mapper is not None:
            info = getattr(mapper.mapped_table, 'info', {})
            bind_key = info.get('bind_key')
            if bind_key is not None:
                return self.binds[mapper.mapped_table]
        return super(BaseSession, self).get_bind(mapper, clause)


class SQLAlchemy(object):

    engines = {}

    def __init__(self, config, session_options=None):
        self._engine_lock = Lock()
        self.config = self._set_defaults(config)
        self.binds = self.config['binds'] # for convenience


        if session_options is None:
            session_options = {}
        session_options.setdefault('scopefunc', get_ident)

        self.Base = self.make_declarative_base()
        self.Session = self.create_scoped_session(session_options)

    @property
    def session(self):
        return self.Session()

    # TODO: adapt this to the hug equivalent
    def init_app(self, app):
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['sqlalchemy'] = self
        # 0.9 and later
        if hasattr(app, 'teardown_appcontext'):
            teardown = app.teardown_appcontext
        # 0.7 to 0.8
        elif hasattr(app, 'teardown_request'):
            teardown = app.teardown_request
        # Older Flask versions
        else:
            if app.config['commit_on_response']:
                raise RuntimeError("Commit on teardown requires Flask >= 0.7")
            teardown = app.after_request

        @teardown
        def shutdown_session(response_or_exc):
            if self.config['commit_on_response']:
                if response_or_exc is None:
                    self.session.commit()
            self.session.remove()
            return response_or_exc

    def _set_defaults(self, config):
        rv = {}
        _prefix = 'sqlalchemy_'
        for k, v in config.items():
            k = k.lower()
            if k.startswith(_prefix):
                rv[k[len(_prefix):]] = v
            #print rv
        rv.setdefault('binds', {None: 'sqlite://'})
        rv.setdefault('native_unicode', True)
        rv.setdefault('echo', False)
        # rv.setdefault('record_queries', None) # not yet
        rv.setdefault('pool_size', None)
        rv.setdefault('pool_timeout', None)
        rv.setdefault('pool_recycle', None)
        rv.setdefault('max_overflow', None)
        rv.setdefault('commit_on_response', False)
        # rv.setdefault('track_modifications', True) # not yet
        return rv

    def _apply_driver_hacks(self, info, options):
        """This method is called before engine creation and used to inject
        driver specific hacks into the options.  The `options` parameter is
        a dictionary of keyword arguments that will then be used to call
        the :func:`create_engine` function.

        The default implementation provides some saner defaults for things
        like pool sizes for MySQL and sqlite.  Also it injects the setting of
        `SQLALCHEMY_NATIVE_UNICODE`.
        """
        if info.drivername.startswith('mysql'):
            info.query.setdefault('charset', 'utf8')
            if info.drivername != 'mysql+gaerdbms':
                options.setdefault('pool_size', 10)
                options.setdefault('pool_recycle', 7200)
        elif info.drivername == 'sqlite':
            pool_size = options.get('pool_size')
            detected_in_memory = False
            # we go to memory and the pool size was explicitly set to 0
            # which is fail.  Let the user know that
            if info.database in (None, '', ':memory:'):
                detected_in_memory = True
                if pool_size == 0:
                    raise RuntimeError('SQLite in memory database with an '
                                       'empty queue not possible due to data '
                                       'loss.')
            # if pool size is None or explicitly set to 0 we assume the
            # user did not want a queue for this sqlite connection and
            # hook in the null pool.
            elif not pool_size:
                from sqlalchemy.pool import NullPool
                options['poolclass'] = NullPool

       
        unu = self.config['native_unicode']
        if unu is None:
            unu = self.use_native_unicode
        if not unu:
            options['use_native_unicode'] = False

    def _apply_pool_defaults(self, options):
        for configkey in ('pool_size', 'pool_timeout', 'pool_recycle', 'max_overflow'):
            value = self.config[configkey]
            if value is not None:
                options[configkey.lower()] = value

    @property
    def metadata(self):
        return self.Base.metadata

    def create_scoped_session(self, options=None):
        if options is None:
            options = {}
        scopefunc = options.pop('scopefunc', None)
        bind = self.get_engine(None)
        options['binds'] = self.get_table_to_bind_map()

        return orm.scoped_session(
                partial(BaseSession, self, bind=bind, **options),
                scopefunc=scopefunc)

    def make_declarative_base(self):
        Base = declarative_base(cls=BaseModel, name='BaseModel', 
                                metaclass=_BoundDeclarativeMeta)
        Base.query = _QueryProperty(self)
        return Base

    def get_engine(self, bind_key):
        with self._engine_lock:
            try:
                return self.engines[bind_key]
            except KeyError:
                # TODO: raise error here if bind not in listed binds
                uri = self.binds[bind_key]
                info = make_url(uri)
                options = {
                    'convert_unicode': True, 
                    'echo': self.config['echo']
                }
                self._apply_pool_defaults(options)
                self._apply_driver_hacks(info, options)
                self.engines[bind_key] = rv = create_engine(
                        info, **options)
                return rv

    def get_tables_for_bind(self, bind_key):
        """Returns a list of all tables relevant for a bind."""
        rv = []
        for table in self.metadata.tables.values():
            if table.info.get('bind_key') == bind_key:
                rv.append(table)
        return rv

    def get_table_to_bind_map(self):
        """Returns a table->bind dictionary. 
        Suitable for use with sessionmaker(binds=db.get_table_to_bind_map()).
        """
        rv = {}
        for bind_key in self.binds.keys():
            engine = self.get_engine(bind_key)
            tables = self.get_tables_for_bind(bind_key)
            rv.update(dict((table, engine) for table in tables))
        return rv

    def _execute_for_all_tables(self, operation, binds='__all__'):

        if binds == '__all__':
            # TODO: raise error here if binds not configured
            binds = self.binds.keys()
        elif binds is None or isinstance(binds, str):
            binds = [binds]

        op = getattr(self.metadata, operation)
        for bind_key in binds:
            op(bind=self.get_engine(bind_key))

    def create_all(self, binds=None):
        """Creates all tables."""
        self._execute_for_all_tables('create_all', binds)

    def drop_all(self, binds=None):
        """Drops all tables"""
        self._execute_for_all_tables('drop_all', binds)

    def reflect(self, binds=None):
        """Reflects tables from the database."""
        self._execute_for_all_tables('reflect', binds)

"""
SQLAlchemy Configs (with their default values):
    SQLALCHEMY_BINDS: {None: 'sqlite://'}
    SQLALCHEMY_NATIVE_UNICODE: True
    SQLALCHEMY_ECHO: False
    SQLALCHEMY_POOL_SIZE: None
    SQLALCHEMY_POOL_TIMEOUT: None
    SQLALCHEMY_POOL_RECYCLE: None
    SQLALCHEMY_MAX_OVERFLOW: None
    SQLALCHEMY_COMMIT_ON_TEARDOWN: False
    # SQLALCHEMY_RECORD_QUERIES: None # not yet
    # SQLALCHEMY_TRACK_MODIFICATIONS: True # not yet
"""
