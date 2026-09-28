// Direct bitmap/sign row engine together with the hardware that feeds it
// from memory.
//
// Weight memories (outside this module, not synthesized): one byte-wide
// memory per stream, each with one synchronous read port. <stream>_rd_en /
// <stream>_rd_addr are sampled at a clock edge; <stream>_rd_data is valid
// after that edge and holds until the next read of that memory.
//
// Row protocol (identical to ternary_five_trit_stream5_fed):
// - start pulses for one cycle with the bit address (byte address and 3-bit
//   offset) of the row's first presence bit and first sign bit
// - PREFILL = 1 idle cycle follows
// - valid is then asserted for GROUPS consecutive cycles with five
//   activations each, and last on the final one; there are no stalls for any
//   weight pattern
// - done pulses with dot one cycle after last, as in the bare engine
//
// The engine reads a 16-bit {next, current} window of each stream. Per stream:
// - the memory output register holds the next byte. The engine advances by
//   at most one byte per cycle (presence: 5 bits, signs: 0..5 bits per group),
//   and on every advance the next byte moves into cur_* while the byte after
//   it is read, arriving exactly when it becomes the next byte. So the sign
//   stream sustains an advance on every cycle without a prefetch buffer.
// - cur_* holds the current byte. It is needed because the memory output is
//   overwritten by the read that fetches the following byte.
// - *_addr holds the byte address after the one in the memory output.
// fill is set during the prefill cycle: the start edge reads the row's first
// byte of each stream, and the prefill edge moves it into cur_* while reading
// the second. One read port with one cycle of latency cannot deliver two
// bytes before the cycle after the second read, so PREFILL = 1 is the minimum.
module ternary_bitcos_stream5_fed #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24,
    parameter int AW = 16
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic [AW+2:0]           start_presence_bit_addr,
    input  logic [AW+2:0]           start_sign_bit_addr,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    output logic                    presence_rd_en,
    output logic [AW-1:0]           presence_rd_addr,
    input  logic [7:0]              presence_rd_data,
    output logic                    sign_rd_en,
    output logic [AW-1:0]           sign_rd_addr,
    input  logic [7:0]              sign_rd_data,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic fill;
    logic [7:0] cur_presence, cur_sign;
    logic [AW-1:0] presence_addr, sign_addr;
    logic advance_presence, advance_sign;
    logic [2:0] presence_offset, sign_offset;

    assign presence_rd_en = start | fill | advance_presence;
    assign presence_rd_addr = start ? start_presence_bit_addr[AW+2:3] : presence_addr;
    assign sign_rd_en = start | fill | advance_sign;
    assign sign_rd_addr = start ? start_sign_bit_addr[AW+2:3] : sign_addr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            fill <= 1'b0;
        else
            fill <= start;
    end

    always_ff @(posedge clk) begin
        if (presence_rd_en)
            presence_addr <= presence_rd_addr + 1'b1;
        if (fill | advance_presence)
            cur_presence <= presence_rd_data;
        if (sign_rd_en)
            sign_addr <= sign_rd_addr + 1'b1;
        if (fill | advance_sign)
            cur_sign <= sign_rd_data;
    end

    ternary_bitcos_stream5_direct_accum #(
        .ACT_W(ACT_W),
        .ACC_W(ACC_W)
    ) engine (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .initial_presence_offset(start_presence_bit_addr[2:0]),
        .initial_sign_offset(start_sign_bit_addr[2:0]),
        .valid(valid),
        .last(last),
        .activations(activations),
        .current_presence_byte(cur_presence),
        .next_presence_byte(presence_rd_data),
        .current_sign_byte(cur_sign),
        .next_sign_byte(sign_rd_data),
        .advance_presence_byte(advance_presence),
        .advance_sign_byte(advance_sign),
        .presence_offset(presence_offset),
        .sign_offset(sign_offset),
        .dot(dot),
        .done(done)
    );
endmodule
