FROM quay.io/redhat-cop/python-kopf-s2i:v1.37

USER 0

COPY . /opt/app-root/src

RUN rm -rf /opt/app-root/src/.git* && \
    chown -R 1001 /opt/app-root/src && \
    chgrp -R 0 /opt/app-root/src && \
    chmod -R g+w /opt/app-root/src

USER 1001

RUN /opt/app-root/src/.s2i/bin/assemble

CMD ["/usr/libexec/s2i/run"]
