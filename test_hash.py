from getpass import getpass

h = getpass("API_HASH: ")

print("Length:", len(h))
print("Valid:", len(h) == 32 and all(
    c in "0123456789abcdefABCDEF" for c in h
))