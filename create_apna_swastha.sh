#!/usr/bin/env bash
} catch {
return res.status(401).json({ error: 'invalid_token' });
}
}


export function requireRole(roles: JwtUser['role'][]) {
return (req: Request, res: Response, next: NextFunction) => {
if (!req.user) return res.status(401).json({ error: 'unauthorized' });
if (!roles.includes(req.user.role)) return res.status(403).json({ error: 'forbidden' });
next();
};
}
EOF


cat > "$ROOTDIR/services/api/src/routes/auth.ts" <<'EOF'
import { Router } from 'express';
import { z } from 'zod';
import otpGenerator from 'otp-generator';
import { db, upsertOtp, verifyOtp } from '../store.js';
import { signUser } from '../jwt.js';


export const authRouter = Router();


const otpReq = z.object({
phone: z.string().min(8),
aadhar: z.string().optional()
});


authRouter.post('/otp/request', (req, res) => {
const parse = otpReq.safeParse(req.body);
if (!parse.success) return res.status(400).json({ error: 'invalid_request' });
const { phone } = parse.data;
const code = otpGenerator.generate(6, { upperCaseAlphabets: false, specialChars: false });
upsertOtp(phone, code);
if ((process.env.OTP_MODE || 'console') === 'console') {
// eslint-disable-next-line no-console
console.log(`OTP ${code} for ${phone}`);
}
res.json({ ok: true });
});


const verifyReq = z.object({
phone: z.string().min(8),
code: z.string().length(6),
role: z.enum(['worker', 'doctor']).default('worker')
});


authRouter.post('/otp/verify', async (req, res) => {
const parse = verifyReq.safeParse(req.body);
if (!parse.success) return res.status(400).json({ error: 'invalid_request' });
const { phone, code, role } = parse.data;
if (!verifyOtp(phone, code)) return res.status(400).json({ error: 'invalid_otp' });


// find or create user
let user = Array.from(db.users.values()).find((u) => u.phone === phone && u.role === role);
if (!user) {
user = { id: `${role}_${phone}`, role, phone };
db.users