"""Acknowledge SQS messages only once their data has been durably loaded."""


def _chunks(entries, size):
    for i in range(0, len(entries), size):
        yield entries[i:i + size]


def load_then_ack(sqs_client, queue_url, receipts, load, batch_size=10):
    """Run load(); delete the receipts if it succeeds, otherwise make them visible
    again so a retry can pick them up. The load error is always the one raised."""
    try:
        load()
    except Exception:
        try:
            for chunk in _chunks(receipts, batch_size):
                sqs_client.change_message_visibility_batch(
                    QueueUrl=queue_url,
                    Entries=[dict(entry, VisibilityTimeout=0) for entry in chunk],
                )
        except Exception as release_error:
            print("WARNING: could not release %d SQS messages: %s" % (len(receipts), release_error))
        raise
    for chunk in _chunks(receipts, batch_size):
        sqs_client.delete_message_batch(QueueUrl=queue_url, Entries=chunk)
